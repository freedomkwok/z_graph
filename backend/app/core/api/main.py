import os
import shutil
import threading
import traceback
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Body, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import Config
from app.core.managers.prompt_label_manager import PromptLabelManager
from app.core.managers.project_manager import ProjectManager
from app.core.managers.task_manager import TaskManager
from app.core.schemas.project import ProjectStatus
from app.core.schemas.task import TaskStatus
from app.core.service.graph_builder import GraphBuilderService
from app.core.service.ontology_generator import OntologyGenerator
from app.core.utils.logger import get_logger
from app.core.utils.text_file_parser import FileParser
from app.core.utils.text_processor import TextProcessor

router = APIRouter()
logger = get_logger("zep_graph.api")

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
ProjectPatchBody = Annotated[dict[str, Any], Body(default_factory=dict)]


class _UploadFileAdapter:
    """Adapter to reuse ProjectManager.save_file_to_project with FastAPI uploads."""

    def __init__(self, upload: UploadFile) -> None:
        self._upload = upload

    def save(self, destination_path: str) -> None:
        self._upload.file.seek(0)
        with open(destination_path, "wb") as output:
            shutil.copyfileobj(self._upload.file, output)


def _error_response(status_code: int, error: str, exc: Exception | None = None) -> JSONResponse:
    payload: dict[str, Any] = {
        "success": False,
        "error": error,
    }
    if exc is not None:
        payload["traceback"] = traceback.format_exc()
    return JSONResponse(status_code=status_code, content=payload)


def allowed_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return ext in FileParser.SUPPORTED_EXTENSIONS


def _build_zep_graph_address(graph_id: str, project_workspace_id: str | None = None) -> str:
    template = str(Config.ZEP_GRAPH_URL_TEMPLATE or "").strip()
    if template:
        if "{graph_id}" in template or "{project_workspace_id}" in template:
            try:
                return template.format(
                    graph_id=graph_id,
                    project_workspace_id=project_workspace_id or "",
                )
            except KeyError:
                return template
        return template
    if project_workspace_id:
        return (
            "https://app.getzep.com/projects/"
            f"{quote(project_workspace_id, safe='')}/graphs/{quote(graph_id, safe='')}"
        )
    # Fallback keeps existing behavior while carrying graph id for deep-link support.
    return f"https://app.getzep.com/?graph_id={quote(graph_id, safe='')}"


@router.get("/project/list")
def list_projects(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    projects = ProjectManager.list_projects(limit=limit)
    return {
        "success": True,
        "data": [p.to_dict() for p in projects],
        "count": len(projects),
    }


@router.get("/prompt-label/list")
def list_prompt_labels() -> dict[str, Any]:
    labels = PromptLabelManager.list_labels()
    return {
        "success": True,
        "data": labels,
        "count": len(labels),
    }


@router.post("/prompt-label")
def create_prompt_label(data: ProjectPatchBody) -> Any:
    try:
        name = (data or {}).get("name")
        label = PromptLabelManager.create_label(str(name or ""))
        return {
            "success": True,
            "message": f"Prompt label saved: {label['name']}",
            "data": label,
        }
    except Exception as exc:
        return _error_response(400, str(exc), exc)


@router.delete("/prompt-label/{label_name}")
def delete_prompt_label(label_name: str) -> Any:
    success, message = PromptLabelManager.delete_label(label_name)
    if not success:
        return _error_response(409, message)
    return {
        "success": True,
        "message": message,
    }


@router.get("/project/{project_id}")
def get_project(project_id: str) -> Any:
    project = ProjectManager.get_project(project_id)
    if not project:
        return _error_response(404, f"Project not found: {project_id}")
    return {
        "success": True,
        "data": project.to_dict(),
    }


@router.patch("/project/{project_id}")
def update_project(project_id: str, data: ProjectPatchBody) -> Any:
    project = ProjectManager.get_project(project_id)
    if not project:
        return _error_response(404, f"Project not found: {project_id}")

    name = str((data or {}).get("name", "")).strip()
    prompt_label = str((data or {}).get("prompt_label", "")).strip()
    if not name and not prompt_label:
        return _error_response(400, "At least one field is required: name or prompt_label")

    if name:
        project.name = name
    if prompt_label:
        project.prompt_label = PromptLabelManager.ensure_label_exists(prompt_label)
    ProjectManager.save_project(project)
    return {
        "success": True,
        "message": f"Project updated: {project_id}",
        "data": project.to_dict(),
    }


@router.delete("/project/{project_id}")
def delete_project(project_id: str) -> Any:
    success = ProjectManager.delete_project(project_id)
    if not success:
        return _error_response(404, f"Project not found or delete failed: {project_id}")
    return {
        "success": True,
        "message": f"Project deleted: {project_id}",
    }


@router.post("/project/{project_id}/reset")
def reset_project(project_id: str) -> Any:
    project = ProjectManager.get_project(project_id)
    if not project:
        return _error_response(404, f"Project not found: {project_id}")

    project.status = ProjectStatus.ONTOLOGY_GENERATED if project.ontology else ProjectStatus.CREATED
    project.zep_graph_id = None
    project.project_workspace_id = None
    project.zep_graph_address = None
    project.graph_build_task_id = None
    project.error = None
    ProjectManager.save_project(project)

    return {
        "success": True,
        "message": f"Project Reset: {project_id}",
        "data": project.to_dict(),
    }


@router.post("/ontology/generate")
def generate_ontology(
    files: list[UploadFile] = File(...),
    simulation_requirement: str = Form(...),
    project_name: str = Form("Unnamed Project"),
    additional_context: str = Form(""),
    prompt_label: str = Form("Production"),
    project_id: str = Form(""),
) -> Any:
    try:
        logger.info("----------------Start generating ontology----------------")

        requirement = (simulation_requirement or "").strip()
        if not requirement:
            return _error_response(400, "Please Provide Simulation Requirement")

        uploaded_files = [f for f in files if f and f.filename]
        if not uploaded_files:
            return _error_response(400, "Upload at least one document file")

        normalized_project_id = str(project_id or "").strip()
        created_new_project = False
        if normalized_project_id:
            project = ProjectManager.get_project(normalized_project_id)
            if not project:
                return _error_response(404, f"Project not found: {normalized_project_id}")
            if project_name and str(project_name).strip():
                project.name = str(project_name).strip()
            logger.info(f"Reusing Project: {project.project_id}")
        else:
            project = ProjectManager.create_project(name=project_name)
            created_new_project = True
            logger.info(f"Created Project: {project.project_id}")

        project.context_requirement = requirement
        project.prompt_label = PromptLabelManager.ensure_label_exists(
            OntologyGenerator._normalize_prompt_label(prompt_label)
        )
        project.error = None

        document_texts: list[str] = []
        all_text = ""

        for upload in uploaded_files:
            if not allowed_file(upload.filename):
                continue

            adapter = _UploadFileAdapter(upload)
            file_info = ProjectManager.save_file_to_project(
                project.project_id,
                adapter,
                upload.filename,
            )
            project.files.append(
                {
                    "filename": file_info["original_filename"],
                    "size": file_info["size"],
                }
            )

            text = FileParser.extract_text(file_info["path"])
            text = TextProcessor.preprocess_text(text)
            if text:
                document_texts.append(text)
                all_text += f"\n\n=== {file_info['original_filename']} ===\n{text}"

        if not document_texts:
            if created_new_project:
                ProjectManager.delete_project(project.project_id)
            return _error_response(400, "not successful, please check file format")

        project.total_text_length = len(all_text)
        ProjectManager.save_extracted_text(project.project_id, all_text)
        logger.info(f"Total Extracted Text: {len(all_text)} Words")

        logger.info("LLM Generating Ontology")
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=document_texts,
            context_requirement=requirement,
            additional_context=additional_context or None,
            prompt_label=project.prompt_label,
        )

        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        logger.info(f"Ontology Generated: {entity_count} Entities, {edge_count} Edges")

        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", []),
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)
        logger.info(f"Ontology Generated Project[{project.project_id}]")

        return {
            "success": True,
            "data": {
                "project_id": project.project_id,
                "project_name": project.name,
                "ontology": project.ontology,
                "analysis_summary": project.analysis_summary,
                "files": project.files,
                "total_text_length": project.total_text_length,
            },
        }
    except Exception as exc:
        logger.exception("Ontology Generation Failed")
        return _error_response(500, str(exc), exc)


@router.post("/build")
def build_graph(data: dict[str, Any] = Body(default_factory=dict)) -> Any:
    try:
        logger.info("----------------Start building graph----------------")

        if not Config.ZEP_API_KEY:
            return _error_response(500, "ZEP_API_KEY not configured")

        project_id = data.get("project_id")
        if not project_id:
            return _error_response(400, "missing project_id")

        project = ProjectManager.get_project(project_id)
        if not project:
            return _error_response(404, f"Project not found: {project_id}")

        force = bool(data.get("force", False))
        if project.status == ProjectStatus.CREATED:
            return _error_response(400, "missing ontology, please refer to /ontology/generate")

        if project.status == ProjectStatus.GRAPH_BUILDING and not force:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Graph is building, force rebuild use `force: true`",
                    "task_id": project.graph_build_task_id,
                },
            )

        if force and project.status in {
            ProjectStatus.GRAPH_BUILDING,
            ProjectStatus.FAILED,
            ProjectStatus.GRAPH_COMPLETED,
        }:
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.zep_graph_id = None
            project.project_workspace_id = None
            project.zep_graph_address = None
            project.graph_build_task_id = None
            project.error = None

        requested_graph_id = str(data.get("graph_id") or "").strip()
        existing_graph_id = str(project.zep_graph_id or "").strip()
        resolved_graph_id = requested_graph_id or existing_graph_id or None

        graph_name = data.get("graph_name", project.name or "imp Graph")
        chunk_size = int(data.get("chunk_size", project.chunk_size or DEFAULT_CHUNK_SIZE))
        chunk_overlap = int(
            data.get("chunk_overlap", project.chunk_overlap or DEFAULT_CHUNK_OVERLAP)
        )

        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap

        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return _error_response(400, "no extracted text")

        ontology = project.ontology
        if not ontology:
            return _error_response(400, "no ontology")

        task_manager = TaskManager()
        task_id = task_manager.create_task(f"build_graph: {graph_name}")
        logger.info(f"create build_graph task: task_id={task_id}, project_id={project_id}")

        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        ProjectManager.save_project(project)

        def build_task() -> None:
            build_logger = get_logger("zep_graph.build")
            try:
                build_logger.info(f"[{task_id}] Start building graph")
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    message="Initializing graph build service",
                )

                builder = GraphBuilderService(backend=Config.ZEP_BACKEND ,api_key=Config.ZEP_API_KEY)

                task_manager.update_task(task_id, message="Splitting Text", progress=5)
                chunks = TextProcessor.split_text(
                    text,
                    chunk_size=chunk_size,
                    overlap=chunk_overlap,
                )
                total_chunks = len(chunks)

                task_manager.update_task(task_id, message="Creating Zep Graph", progress=10)
                graph_id, project_workspace_id = builder.create_graph(
                    name=graph_name,
                    project_id=project_id,
                    graph_id=resolved_graph_id,
                )

                project.zep_graph_id = graph_id
                project.project_workspace_id = project_workspace_id
                project.zep_graph_address = _build_zep_graph_address(
                    graph_id, project_workspace_id=project_workspace_id
                )
                ProjectManager.save_project(project)

                task_manager.update_task(task_id, message="Setting Ontology", progress=15)
                builder.set_ontology(graph_id, ontology)

                def add_progress_callback(message: str, progress_ratio: float) -> None:
                    progress = 15 + int(progress_ratio * 40)
                    task_manager.update_task(task_id, message=message, progress=progress)

                task_manager.update_task(
                    task_id,
                    message=f"Adding {total_chunks} chunks",
                    progress=15,
                )
                episode_uuids = builder.add_text_batches(
                    graph_id,
                    chunks,
                    batch_size=3,
                    progress_callback=add_progress_callback,
                )

                task_manager.update_task(task_id, message="Waiting for Zep to process data", progress=45)

                def wait_progress_callback(message: str, progress_ratio: float) -> None:
                    progress = 55 + int(progress_ratio * 35)
                    task_manager.update_task(task_id, message=message, progress=progress)

                builder._wait_for_episodes(episode_uuids, wait_progress_callback)

                task_manager.update_task(task_id, message="Getting Graph Data", progress=90)
                graph_data = builder.get_graph_data(graph_id, include_episode_data=False)

                project.status = ProjectStatus.GRAPH_COMPLETED
                ProjectManager.save_project(project)

                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(
                    f"[{task_id}] Graph Build Completed: graph_id={graph_id}, nodes={node_count}, edges={edge_count}"
                )

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message="Graph Build Completed",
                    progress=100,
                    result={
                        "project_id": project_id,
                        "zep_graph_id": graph_id,
                        "project_workspace_id": project_workspace_id,
                        "zep_graph_address": project.zep_graph_address,
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "chunk_count": total_chunks,
                    },
                )
            except Exception as exc:
                build_logger.error(f"[{task_id}] Graph Build Failed: {exc}")
                build_logger.debug(traceback.format_exc())

                project.status = ProjectStatus.FAILED
                project.error = str(exc)
                ProjectManager.save_project(project)

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=f"Graph Build Failed: {exc}",
                    error=traceback.format_exc(),
                )

        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()

        return {
            "success": True,
            "data": {
                "project_id": project_id,
                "task_id": task_id,
                "message": "Graph Build Task Started, please refer to /task/{task_id} for progress",
            },
        }
    except Exception as exc:
        logger.exception("Graph Build Request Failed")
        return _error_response(500, str(exc), exc)


@router.get("/task/{task_id}")
def get_task(task_id: str) -> Any:
    task = TaskManager().get_task(task_id)
    if not task:
        return _error_response(404, f"Task not found: {task_id}")
    return {
        "success": True,
        "data": task.to_dict(),
    }


@router.get("/tasks")
def list_tasks() -> dict[str, Any]:
    tasks = TaskManager().list_tasks()
    return {
        "success": True,
        "data": tasks,
        "count": len(tasks),
    }


@router.get("/data/{graph_id}")
def get_graph_data(
    graph_id: str,
    include_episode_data: bool = Query(default=True),
) -> Any:
    try:
        if not Config.ZEP_API_KEY:
            return _error_response(500, "ZEP_API_KEY not configured")

        builder = GraphBuilderService(backend=Config.ZEP_BACKEND ,api_key=Config.ZEP_API_KEY)
        graph_data = builder.get_graph_data(
            graph_id,
            include_episode_data=include_episode_data,
        )
        return {
            "success": True,
            "data": graph_data,
        }
    except Exception as exc:
        logger.exception("Failed to get graph data")
        return _error_response(500, str(exc), exc)


@router.delete("/delete/{graph_id}")
def delete_graph(graph_id: str) -> Any:
    try:
        if not Config.ZEP_API_KEY:
            return _error_response(500, "ZEP_API_KEY not configured")

        builder = GraphBuilderService(backend=Config.ZEP_BACKEND ,api_key=Config.ZEP_API_KEY)
        builder.delete_graph(graph_id)
        return {
            "success": True,
            "message": f"Graph deleted: {graph_id}",
        }
    except Exception as exc:
        logger.exception("Failed to delete graph")
        return _error_response(500, str(exc), exc)
