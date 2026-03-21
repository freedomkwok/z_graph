"""
Zep retrieval helpers for the report agent: graph search, node/edge reads, and related tools.

Primary tools (optimized):
1. InsightForge - deep hybrid retrieval with sub-questions
2. PanoramaSearch - full view including stale content
3. QuickSearch - lightweight search
"""

from typing import Dict, Any, List, Optional

from zep_cloud.client import Zep

from app.core.config import Config
from app.core.schemas.zep_operation import (
    EdgeInfo,
    InsightForgeResult,
    NodeInfo,
    PanoramaResult,
    SearchResult,
)
from app.core.utils.logger import get_logger
from app.core.utils.llm_client import LLMClient
from app.core.utils.retry import call_with_retry
from app.core.utils.zep_paging import fetch_all_nodes, fetch_all_edges

logger = get_logger('imp_graph.zep_tools')

class ZepToolsService:
    """
    Facade for Zep-backed tools.

    Core: insight_forge, panorama_search, quick_search.
    Basics: search_graph, get_all_nodes/edges, get_node_detail/edges,
    get_entities_by_type, get_entity_summary.
    """
    
    # Retry policy
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    
    def __init__(self, api_key: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY 未配置")
        
        self.client = Zep(api_key=self.api_key)
        # Lazy LLM for InsightForge sub-queries
        self._llm_client = llm_client
        logger.info("ZepToolsService 初始化完成")
    
    @property
    def llm(self) -> LLMClient:
        """Lazy LLM client."""
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client
    
    def _call_with_retry(self, func, operation_name: str, max_retries: int = None):
        """Call Zep with tenacity-based exponential backoff."""
        retries = max_retries or self.MAX_RETRIES
        try:
            return call_with_retry(
                func=func,
                operation_name=f"Zep {operation_name}",
                logger=logger,
                max_retries=retries,
                initial_delay=self.RETRY_DELAY,
            )
        except Exception as e:
            logger.error(f"Zep {operation_name} failed after {retries} attempts: {str(e)}")
            raise
    
    def search_graph(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        Hybrid graph search (semantic + BM25). Falls back to local keyword match if Zep search fails.

        Args:
            graph_id: Standalone graph id
            query: Query string
            limit: Max hits
            scope: "edges" or "nodes"

        Returns:
            SearchResult
        """
        logger.info(f"图谱搜索: graph_id={graph_id}, query={query[:50]}...")
        
        # Prefer Zep Cloud search API
        try:
            search_results = self._call_with_retry(
                func=lambda: self.client.graph.search(
                    graph_id=graph_id,
                    query=query,
                    limit=limit,
                    scope=scope,
                    reranker="cross_encoder"
                ),
                operation_name=f"图谱搜索(graph={graph_id})"
            )
            
            facts = []
            edges = []
            nodes = []
            
            if hasattr(search_results, 'edges') and search_results.edges:
                for edge in search_results.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        facts.append(edge.fact)
                    edges.append({
                        "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                        "name": getattr(edge, 'name', ''),
                        "fact": getattr(edge, 'fact', ''),
                        "source_node_uuid": getattr(edge, 'source_node_uuid', ''),
                        "target_node_uuid": getattr(edge, 'target_node_uuid', ''),
                    })
            
            if hasattr(search_results, 'nodes') and search_results.nodes:
                for node in search_results.nodes:
                    nodes.append({
                        "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                        "name": getattr(node, 'name', ''),
                        "labels": getattr(node, 'labels', []),
                        "summary": getattr(node, 'summary', ''),
                    })
                    if hasattr(node, 'summary') and node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(f"搜索完成: 找到 {len(facts)} 条相关事实")
            
            return SearchResult(
                facts=facts,
                edges=edges,
                nodes=nodes,
                query=query,
                total_count=len(facts)
            )
            
        except Exception as e:
            logger.warning(f"Zep Search API失败，降级为本地搜索: {str(e)}")
            return self._local_search(graph_id, query, limit, scope)
    
    def _local_search(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        Fallback keyword search over fetched edges/nodes.

        Args:
            graph_id: Graph id
            query: Query string
            limit: Max hits
            scope: edges / nodes / both

        Returns:
            SearchResult
        """
        logger.info(f"使用本地搜索: query={query[:30]}...")
        
        facts = []
        edges_result = []
        nodes_result = []
        
        # Tokenize query (lightweight)
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        
        def match_score(text: str) -> int:
            """Heuristic relevance score."""
            if not text:
                return 0
            text_lower = text.lower()
            if query_lower in text_lower:
                return 100
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 10
            return score
        
        try:
            if scope in ["edges", "both"]:
                all_edges = self.get_all_edges(graph_id)
                scored_edges = []
                for edge in all_edges:
                    score = match_score(edge.fact) + match_score(edge.name)
                    if score > 0:
                        scored_edges.append((score, edge))
                
                scored_edges.sort(key=lambda x: x[0], reverse=True)
                
                for score, edge in scored_edges[:limit]:
                    if edge.fact:
                        facts.append(edge.fact)
                    edges_result.append({
                        "uuid": edge.uuid,
                        "name": edge.name,
                        "fact": edge.fact,
                        "source_node_uuid": edge.source_node_uuid,
                        "target_node_uuid": edge.target_node_uuid,
                    })
            
            if scope in ["nodes", "both"]:
                all_nodes = self.get_all_nodes(graph_id)
                scored_nodes = []
                for node in all_nodes:
                    score = match_score(node.name) + match_score(node.summary)
                    if score > 0:
                        scored_nodes.append((score, node))
                
                scored_nodes.sort(key=lambda x: x[0], reverse=True)
                
                for score, node in scored_nodes[:limit]:
                    nodes_result.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "labels": node.labels,
                        "summary": node.summary,
                    })
                    if node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(f"本地搜索完成: 找到 {len(facts)} 条相关事实")
            
        except Exception as e:
            logger.error(f"本地搜索失败: {str(e)}")
        
        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query,
            total_count=len(facts)
        )
    
    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        """
        All nodes (paged fetch).

        Args:
            graph_id: Graph id

        Returns:
            NodeInfo list
        """
        logger.info(f"获取图谱 {graph_id} 的所有节点...")

        nodes = fetch_all_nodes(self.client, graph_id)

        result = []
        for node in nodes:
            node_uuid = getattr(node, 'uuid_', None) or getattr(node, 'uuid', None) or ""
            result.append(NodeInfo(
                uuid=str(node_uuid) if node_uuid else "",
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            ))

        logger.info(f"获取到 {len(result)} 个节点")
        return result

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        """
        All edges (paged).

        Args:
            graph_id: Graph id
            include_temporal: Populate temporal fields when True

        Returns:
            EdgeInfo list
        """
        logger.info(f"获取图谱 {graph_id} 的所有边...")

        edges = fetch_all_edges(self.client, graph_id)

        result = []
        for edge in edges:
            edge_uuid = getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', None) or ""
            edge_info = EdgeInfo(
                uuid=str(edge_uuid) if edge_uuid else "",
                name=edge.name or "",
                fact=edge.fact or "",
                source_node_uuid=edge.source_node_uuid or "",
                target_node_uuid=edge.target_node_uuid or ""
            )

            if include_temporal:
                edge_info.created_at = getattr(edge, 'created_at', None)
                edge_info.valid_at = getattr(edge, 'valid_at', None)
                edge_info.invalid_at = getattr(edge, 'invalid_at', None)
                edge_info.expired_at = getattr(edge, 'expired_at', None)

            result.append(edge_info)

        logger.info(f"获取到 {len(result)} 条边")
        return result
    
    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        """
        Single node by UUID.

        Args:
            node_uuid: Node UUID

        Returns:
            NodeInfo or None
        """
        logger.info(f"获取节点详情: {node_uuid[:8]}...")
        
        try:
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=node_uuid),
                operation_name=f"获取节点详情(uuid={node_uuid[:8]}...)"
            )
            
            if not node:
                return None
            
            return NodeInfo(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            )
        except Exception as e:
            logger.error(f"获取节点详情失败: {str(e)}")
            return None
    
    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        """
        Edges incident on a node (filters full edge list).

        Args:
            graph_id: Graph id
            node_uuid: Node UUID

        Returns:
            EdgeInfo list
        """
        logger.info(f"获取节点 {node_uuid[:8]}... 的相关边")
        
        try:
            all_edges = self.get_all_edges(graph_id)
            
            result = []
            for edge in all_edges:
                if edge.source_node_uuid == node_uuid or edge.target_node_uuid == node_uuid:
                    result.append(edge)
            
            logger.info(f"找到 {len(result)} 条与节点相关的边")
            return result
            
        except Exception as e:
            logger.warning(f"获取节点边失败: {str(e)}")
            return []
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str
    ) -> List[NodeInfo]:
        """
        Nodes whose labels include the given ontology type.

        Args:
            graph_id: Graph id
            entity_type: Label name (e.g. Student)

        Returns:
            Matching NodeInfo rows
        """
        logger.info(f"获取类型为 {entity_type} 的实体...")
        
        all_nodes = self.get_all_nodes(graph_id)
        
        filtered = []
        for node in all_nodes:
            if entity_type in node.labels:
                filtered.append(node)
        
        logger.info(f"找到 {len(filtered)} 个 {entity_type} 类型的实体")
        return filtered
    
    def get_entity_summary(
        self, 
        graph_id: str, 
        entity_name: str
    ) -> Dict[str, Any]:
        """
        Bundle search hits plus edges for a named entity.

        Args:
            graph_id: Graph id
            entity_name: Node display name

        Returns:
            Dict with facts and edges
        """
        logger.info(f"获取实体 {entity_name} 的关系摘要...")
        
        search_result = self.search_graph(
            graph_id=graph_id,
            query=entity_name,
            limit=20
        )
        
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = None
        for node in all_nodes:
            if node.name.lower() == entity_name.lower():
                entity_node = node
                break
        
        related_edges = []
        if entity_node:
            related_edges = self.get_node_edges(graph_id, entity_node.uuid)
        
        return {
            "entity_name": entity_name,
            "entity_info": entity_node.to_dict() if entity_node else None,
            "related_facts": search_result.facts,
            "related_edges": [e.to_dict() for e in related_edges],
            "total_relations": len(related_edges)
        }
    
    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        """
        Label and relation name histograms.

        Args:
            graph_id: Graph id

        Returns:
            Count dicts
        """
        logger.info(f"获取图谱 {graph_id} 的统计信息...")
        
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        
        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1
        
        relation_types = {}
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1
        
        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types
        }
    
    # --- Advanced retrieval tools ---
    
    def insight_forge(
        self,
        graph_id: str,
        query: str,
        context_hint: str = "",
        report_context: str = "",
        max_sub_queries: int = 5
    ) -> InsightForgeResult:
        """
        Multi-step retrieval: LLM sub-queries, semantic search, entity cards, relation chains.

        Args:
            graph_id: Graph id
            query: User question
            context_hint: Optional context hint to guide sub-query generation
            report_context: Optional extra context for sub-query generation
            max_sub_queries: Max sub-queries

        Returns:
            InsightForgeResult
        """
        logger.info(f"InsightForge 深度洞察检索: {query[:50]}...")
        
        result = InsightForgeResult(
            query=query,
            context_hint=context_hint,
            sub_queries=[]
        )
        
        sub_queries = self._generate_sub_queries(
            query=query,
            context_hint=context_hint,
            report_context=report_context,
            max_queries=max_sub_queries
        )
        result.sub_queries = sub_queries
        logger.info(f"生成 {len(sub_queries)} 个子问题")
        
        all_facts = []
        all_edges = []
        seen_facts = set()
        
        for sub_query in sub_queries:
            search_result = self.search_graph(
                graph_id=graph_id,
                query=sub_query,
                limit=15,
                scope="edges"
            )
            
            for fact in search_result.facts:
                if fact not in seen_facts:
                    all_facts.append(fact)
                    seen_facts.add(fact)
            
            all_edges.extend(search_result.edges)
        
        main_search = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=20,
            scope="edges"
        )
        for fact in main_search.facts:
            if fact not in seen_facts:
                all_facts.append(fact)
                seen_facts.add(fact)
        
        result.semantic_facts = all_facts
        result.total_facts = len(all_facts)
        
        entity_uuids = set()
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                if source_uuid:
                    entity_uuids.add(source_uuid)
                if target_uuid:
                    entity_uuids.add(target_uuid)
        
        entity_insights = []
        node_map = {}
        
        for uuid in list(entity_uuids):
            if not uuid:
                continue
            try:
                node = self.get_node_detail(uuid)
                if node:
                    node_map[uuid] = node
                    entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "实体")
                    
                    related_facts = [
                        f for f in all_facts 
                        if node.name.lower() in f.lower()
                    ]
                    
                    entity_insights.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "type": entity_type,
                        "summary": node.summary,
                        "related_facts": related_facts
                    })
            except Exception as e:
                logger.debug(f"获取节点 {uuid} 失败: {e}")
                continue
        
        result.entity_insights = entity_insights
        result.total_entities = len(entity_insights)
        
        relationship_chains = []
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                relation_name = edge_data.get('name', '')
                
                source_name = node_map.get(source_uuid, NodeInfo('', '', [], '', {})).name or source_uuid[:8]
                target_name = node_map.get(target_uuid, NodeInfo('', '', [], '', {})).name or target_uuid[:8]
                
                chain = f"{source_name} --[{relation_name}]--> {target_name}"
                if chain not in relationship_chains:
                    relationship_chains.append(chain)
        
        result.relationship_chains = relationship_chains
        result.total_relationships = len(relationship_chains)
        
        logger.info(f"InsightForge完成: {result.total_facts}条事实, {result.total_entities}个实体, {result.total_relationships}条关系")
        return result
    
    def _generate_sub_queries(
        self,
        query: str,
        context_hint: str = "",
        report_context: str = "",
        max_queries: int = 5
    ) -> List[str]:
        """
        Ask the LLM for sub-queries (JSON list).
        """
        system_prompt = """你是一个专业的问题分析专家。你的任务是将一个复杂问题分解为多个可独立检索的子问题。

要求：
1. 每个子问题应该足够具体，能直接用于知识图谱检索
2. 子问题应该覆盖原问题的不同维度（如：谁、什么、为什么、怎么样、何时、何地）
3. 子问题要与提供的背景上下文相关（若有）
4. 返回JSON格式：{"sub_queries": ["子问题1", "子问题2", ...]}"""

        user_prompt = f"""背景上下文：
{context_hint if context_hint else "未提供"}

{f"报告上下文：{report_context[:500]}" if report_context else ""}

请将以下问题分解为{max_queries}个子问题：
{query}

返回JSON格式的子问题列表。"""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            sub_queries = response.get("sub_queries", [])
            return [str(sq) for sq in sub_queries[:max_queries]]
            
        except Exception as e:
            logger.warning(f"生成子问题失败: {str(e)}，使用默认子问题")
            return [
                query,
                f"{query} 的主要参与者",
                f"{query} 的原因和影响",
                f"{query} 的发展过程"
            ][:max_queries]
    
    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50
    ) -> PanoramaResult:
        """
        Full graph snapshot with active vs historical facts split by temporal flags.

        Args:
            graph_id: Graph id
            query: Query string for relevance ranking
            include_expired: Include historical bucket
            limit: Max facts per bucket

        Returns:
            PanoramaResult
        """
        logger.info(f"PanoramaSearch 广度搜索: {query[:50]}...")
        
        result = PanoramaResult(query=query)
        
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}
        result.all_nodes = all_nodes
        result.total_nodes = len(all_nodes)
        
        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_edges = all_edges
        result.total_edges = len(all_edges)
        
        active_facts = []
        historical_facts = []
        
        for edge in all_edges:
            if not edge.fact:
                continue
            
            source_name = node_map.get(edge.source_node_uuid, NodeInfo('', '', [], '', {})).name or edge.source_node_uuid[:8]
            target_name = node_map.get(edge.target_node_uuid, NodeInfo('', '', [], '', {})).name or edge.target_node_uuid[:8]
            
            is_historical = edge.is_expired or edge.is_invalid
            
            if is_historical:
                valid_at = edge.valid_at or "未知"
                invalid_at = edge.invalid_at or edge.expired_at or "未知"
                fact_with_time = f"[{valid_at} - {invalid_at}] {edge.fact}"
                historical_facts.append(fact_with_time)
            else:
                active_facts.append(edge.fact)
        
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        
        def relevance_score(fact: str) -> int:
            fact_lower = fact.lower()
            score = 0
            if query_lower in fact_lower:
                score += 100
            for kw in keywords:
                if kw in fact_lower:
                    score += 10
            return score
        
        active_facts.sort(key=relevance_score, reverse=True)
        historical_facts.sort(key=relevance_score, reverse=True)
        
        result.active_facts = active_facts[:limit]
        result.historical_facts = historical_facts[:limit] if include_expired else []
        result.active_count = len(active_facts)
        result.historical_count = len(historical_facts)
        
        logger.info(f"PanoramaSearch完成: {result.active_count}条有效, {result.historical_count}条历史")
        return result
    
    def quick_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
        Thin wrapper around search_graph (edges scope).

        Args:
            graph_id: Graph id
            query: Query string
            limit: Max hits

        Returns:
            SearchResult
        """
        logger.info(f"QuickSearch 简单搜索: {query[:50]}...")
        
        result = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope="edges"
        )
        
        logger.info(f"QuickSearch完成: {result.total_count}条结果")
        return result
    
