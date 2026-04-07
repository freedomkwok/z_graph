import os
import traceback
from typing import Annotated, Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.core.managers.project_manager import ProjectManager
from app.core.managers.prompt_label_manager import PromptLabelManager
from app.core.utils.logger import get_logger
from app.core.utils.text_file_parser import FileParser
from app.core.utils.text_processor import TextProcessor

router = APIRouter()
logger = get_logger("z_graph.api.prompt_labels")
ProjectPatchBody = Annotated[dict[str, Any], Body(default_factory=dict)]


def _error_response(status_code: int, error: str, exc: Exception | None = None) -> JSONResponse:
    payload: dict[str, Any] = {
        "success": False,
        "error": error,
    }
    if exc is not None:
        payload["traceback"] = traceback.format_exc()
    return JSONResponse(status_code=status_code, content=payload)


def _extract_project_document_texts(project_id: str) -> tuple[list[str], list[str]]:
    project = ProjectManager.get_project(project_id)
    if project is None:
        raise ValueError(f"Project not found: {project_id}")

    document_texts: list[str] = []
    processed_files: list[str] = []
    for file_path in ProjectManager.get_project_files(project_id):
        extension = os.path.splitext(file_path)[1].lower()
        if extension not in FileParser.SUPPORTED_EXTENSIONS:
            continue

        try:
            extracted_text = FileParser.extract_text(file_path)
            extracted_text = TextProcessor.preprocess_text(extracted_text)
        except Exception as exc:
            logger.warning("Skip unreadable project file '%s': %s", file_path, str(exc))
            continue

        if not extracted_text:
            continue
        document_texts.append(extracted_text)
        processed_files.append(os.path.basename(file_path))

    if document_texts:
        return document_texts, processed_files

    # Keep compatibility for projects that only persisted extracted text.
    persisted_text = TextProcessor.preprocess_text(
        ProjectManager.get_extracted_text(project_id) or ""
    )
    if persisted_text:
        return [persisted_text], processed_files

    raise ValueError(
        "No readable uploaded documents found for this project. "
        "Please run Step A (Ontology Generate) with files first."
    )


@router.get("/prompt-label/list")
def list_prompt_labels() -> dict[str, Any]:
    labels = PromptLabelManager.list_labels()
    label_stats = PromptLabelManager.get_label_stats()
    total_labels = int(label_stats.get("total_labels") or len(labels))
    return {
        "success": True,
        "data": labels,
        "count": len(labels),
        "total_labels": total_labels,
        "stats": label_stats,
    }


@router.post("/prompt-label")
def create_prompt_label(data: ProjectPatchBody) -> Any:
    try:
        name = (data or {}).get("name")
        label = PromptLabelManager.create_label(str(name or ""))
        return {
            "success": True,
            "message": f"Category label saved: {label['name']}",
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


@router.post("/prompt-label/{label_name}/sync-from-langfuse")
def sync_prompt_label_from_langfuse(label_name: str) -> Any:
    try:
        result = PromptLabelManager.sync_label_from_langfuse(label_name)
        return {
            "success": True,
            "message": f"Category label synced from Langfuse: {result.get('requested_label')}",
            "data": result,
        }
    except Exception as exc:
        logger.exception("Category label sync from Langfuse failed")
        return _error_response(500, str(exc), exc)


@router.get("/prompt-label/{label_name}/types")
def get_prompt_label_types(label_name: str) -> Any:
    try:
        data = PromptLabelManager.get_label_type_lists(label_name)
        return {
            "success": True,
            "data": data,
        }
    except Exception as exc:
        return _error_response(400, str(exc), exc)


@router.patch("/prompt-label/{label_name}/types")
def update_prompt_label_types(label_name: str, data: ProjectPatchBody) -> Any:
    try:
        result = PromptLabelManager.update_label_type_lists(label_name, data)
        return {
            "success": True,
            "message": f"Category label type lists updated: {result.get('label_name')}",
            "data": result,
        }
    except ValueError as exc:
        return _error_response(400, str(exc))
    except Exception as exc:
        logger.exception("Category label type update failed")
        return _error_response(500, str(exc), exc)


@router.get("/prompt-label/{label_name}/prompt-template/{prompt_key}")
def get_prompt_label_prompt_template(label_name: str, prompt_key: str) -> Any:
    try:
        result = PromptLabelManager.get_label_prompt_template(label_name, prompt_key)
        return {
            "success": True,
            "data": result,
        }
    except ValueError as exc:
        return _error_response(400, str(exc))
    except Exception as exc:
        return _error_response(500, str(exc), exc)


@router.patch("/prompt-label/{label_name}/prompt-template/{prompt_key}")
def update_prompt_label_prompt_template(
    label_name: str,
    prompt_key: str,
    data: ProjectPatchBody,
) -> Any:
    try:
        payload = data or {}
        result = PromptLabelManager.update_label_prompt_template(
            label_name=label_name,
            prompt_key=prompt_key,
            content=payload.get("content", ""),
        )
        return {
            "success": True,
            "message": f"Prompt template updated: {result.get('prompt_key')}",
            "data": result,
        }
    except ValueError as exc:
        return _error_response(400, str(exc))
    except Exception as exc:
        logger.exception("Prompt template update failed")
        return _error_response(500, str(exc), exc)


@router.post("/prompt-label/{label_name}/prompt-template/{prompt_key}/sync-from-default")
def sync_prompt_label_prompt_template_from_default(label_name: str, prompt_key: str) -> Any:
    try:
        result = PromptLabelManager.sync_label_prompt_template_from_default(
            label_name=label_name,
            prompt_key=prompt_key,
        )
        return {
            "success": True,
            "message": f"Prompt template synced from Production: {result.get('prompt_key')}",
            "data": result,
        }
    except ValueError as exc:
        return _error_response(400, str(exc))
    except Exception as exc:
        logger.exception("Prompt template sync from default failed")
        return _error_response(500, str(exc), exc)


@router.post("/prompt-label/{label_name}/generate-from-llm")
def generate_prompt_label_types_from_llm(label_name: str, data: ProjectPatchBody) -> Any:
    try:
        payload = data or {}
        project_id = str(payload.get("project_id") or "").strip()
        if not project_id:
            return _error_response(400, "project_id is required")
        entity_edge_generator_prompt_content = payload.get("entity_edge_generator_prompt_content")

        document_texts, processed_files = _extract_project_document_texts(project_id)
        result = PromptLabelManager.generate_label_type_lists_from_documents(
            label_name,
            document_texts=document_texts,
            project_id=project_id,
            entity_edge_generator_prompt_content=entity_edge_generator_prompt_content,
        )
        return {
            "success": True,
            "message": f"Category label generated by LLM: {result.get('label_name')}",
            "data": {
                **result,
                "project_id": project_id,
                "processed_documents": len(document_texts),
                "processed_files": processed_files,
            },
        }
    except ValueError as exc:
        return _error_response(400, str(exc))
    except Exception as exc:
        logger.exception("Category label LLM generation failed")
        return _error_response(500, str(exc), exc)
