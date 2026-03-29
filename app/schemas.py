from typing import Literal, Optional

from pydantic import BaseModel, Field


ActionType = Literal[
    "create_folder",
    "move_bookmark",
    "rename_bookmark",
    "rename_folder",
]


class BookmarkItem(BaseModel):
    id: str
    title: str
    url: str
    path: list[str]
    parentId: Optional[str] = None


class FolderItem(BaseModel):
    id: str
    title: str
    path: list[str]
    parentId: Optional[str] = None


class BookmarkContext(BaseModel):
    bookmarks: list[BookmarkItem] = Field(default_factory=list)
    folders: list[FolderItem] = Field(default_factory=list)


class BookmarkPlanRequest(BaseModel):
    requestId: str
    clientId: str
    instruction: str
    context: BookmarkContext


class PlanAction(BaseModel):
    actionId: str
    type: ActionType
    title: Optional[str] = None
    parentId: Optional[str] = None
    parentPath: Optional[list[str]] = None
    bookmarkId: Optional[str] = None
    folderId: Optional[str] = None
    targetFolderId: Optional[str] = None
    targetPath: Optional[list[str]] = None
    newTitle: Optional[str] = None


class BookmarkPlanResponse(BaseModel):
    summary: str
    warnings: list[str] = Field(default_factory=list)
    actions: list[PlanAction] = Field(default_factory=list)


class UsageResponse(BaseModel):
    limit: int
    used: int
    remaining: int
    date: str
