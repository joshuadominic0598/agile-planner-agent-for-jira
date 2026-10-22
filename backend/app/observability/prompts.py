"""Project prompt history shared by the agent and evaluation workspace."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..agent import prompt_versions

router = APIRouter(prefix='/api/ops/evaluation/prompts', tags=['Prompt versions'])


@router.get('/{dataset_id}')
def catalog(dataset_id: str):
    return prompt_versions.catalog(dataset_id)


@router.post('/{dataset_id}', status_code=201)
def save(dataset_id: str, body: prompt_versions.PromptWrite):
    return prompt_versions.save(dataset_id, body)


class Activation(BaseModel):
    version_id: str = Field(max_length=100)


@router.post('/{dataset_id}/activate')
def activate(dataset_id: str, body: Activation):
    return prompt_versions.activate(dataset_id, body.version_id)
