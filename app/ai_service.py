import json
import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.schemas import BookmarkPlanRequest, BookmarkPlanResponse, PlanAction


logger = logging.getLogger(__name__)
MAX_NORMALIZED_ACTIONS = 24


SYSTEM_PROMPT = """
你是一个书签整理助手。你的任务不是输出自然语言步骤，而是输出严格 JSON。

只允许返回以下动作类型：
- create_folder
- move_bookmark
- rename_bookmark
- rename_folder

要求：
1. 不要返回 markdown。
2. 不要返回代码块。
3. 只返回一个 JSON 对象。
4. JSON 顶层必须包含 summary、warnings、actions。
5. actions 必须是数组。
6. 第一版不要输出任何 delete 或 move_folder 动作。
7. 如果目标文件夹是新建文件夹，优先使用 parentPath / targetPath，不要虚构 folderId。
8. 任何 move_bookmark 动作之前，必须确保 targetPath 已存在；如果目标目录不存在，先输出缺失层级的 create_folder 动作，再输出 move_bookmark。
9. 如果需要创建多级目录，必须按父目录到子目录的顺序逐级创建，禁止跳级创建。
10. 依赖新目录的动作必须排在 create_folder 之后，保证前端按顺序执行时不会失败。
11. 如果上下文里已经存在对应目录，不要重复 create_folder。
12. 优先复用已有目录；只有在确实不存在时才创建新目录。
13. 所有 key 必须使用双引号，禁止单引号、中文引号、无引号 key、注释、尾逗号。
14. 任何字符串值内部如需出现双引号，必须使用反斜杠转义。
15. 除 JSON 之外不要输出任何解释、前缀、后缀、思考过程或致歉文本。
16. 如果没有合适动作，返回 {"summary":"...", "warnings":["..."], "actions":[]}。
17. 动作数量要克制，只输出真正必要的动作；不要为了“看起来完整”而重复创建、重复移动或重复重命名。
18. 同一对象最多输出一个最终重命名动作；如果多次修改同一对象，只保留最终结果。
19. 同一书签最多输出一个最终移动动作；禁止对同一书签重复 move_bookmark。
20. 非必要不要重命名；只有当标题明显更清晰、更短或更规范时才输出 rename 动作。
""".strip()


REPAIR_PROMPT = """
你是一个 JSON 修复器。你的任务是把用户提供的内容修复成严格合法的 JSON。

要求：
1. 只返回一个 JSON 对象。
2. 不要返回 markdown。
3. 不要返回代码块。
4. 保留原始语义，不要新增用户未表达的动作。
5. 顶层必须包含 summary、warnings、actions。
6. 所有属性名必须用双引号包裹。
7. 去掉尾逗号、注释、无效字符和多余说明文字。
8. 把中文引号、全角冒号、全角逗号修复成标准 JSON。
9. 如果 actions 缺失，补成空数组；如果 warnings 缺失，补成空数组。
""".strip()


def build_user_prompt(payload: BookmarkPlanRequest) -> str:
    return json.dumps(
        {
            "instruction": payload.instruction,
            "context": payload.context.model_dump(),
            "planning_rules": {
                "prefer_minimal_actions": True,
                "avoid_duplicate_actions": True,
                "max_actions": MAX_NORMALIZED_ACTIONS,
            },
            "response_schema": {
                "summary": "string",
                "warnings": ["string"],
                "actions": [
                    {
                        "actionId": "string",
                        "type": "create_folder | move_bookmark | rename_bookmark | rename_folder",
                        "title": "string | optional",
                        "parentId": "string | optional",
                        "parentPath": ["string"],
                        "bookmarkId": "string | optional",
                        "folderId": "string | optional",
                        "targetFolderId": "string | optional",
                        "targetPath": ["string"],
                        "newTitle": "string | optional",
                    }
                ],
            },
        },
        ensure_ascii=False,
    )


async def generate_plan(payload: BookmarkPlanRequest) -> BookmarkPlanResponse:
    if not settings.api_key:
        raise RuntimeError("Missing AI_API_KEY")

    request_body: dict[str, Any] = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(payload)},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        response = await client.post(
            f"{settings.api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        response.raise_for_status()
        data = response.json()

    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    try:
        plan = parse_plan_content(content)
    except ValueError as initial_error:
        logger.warning("Initial plan parse failed: %s", initial_error)
        repaired_content = await repair_plan_content(content)
        try:
            plan = parse_plan_content(repaired_content)
        except ValueError as repaired_error:
            logger.warning("Repaired plan parse failed: %s", repaired_error)
            plan = build_fallback_plan(content, repaired_content, repaired_error)

    plan = normalize_plan(plan, payload)

    return BookmarkPlanResponse(
        summary=plan.get("summary", "AI 已生成整理建议。"),
        warnings=plan.get("warnings", []),
        actions=[PlanAction(**action) for action in plan.get("actions", [])],
    )


async def repair_plan_content(content: str) -> str:
    request_body: dict[str, Any] = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": REPAIR_PROMPT},
            {"role": "user", "content": content},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        response = await client.post(
            f"{settings.api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        response.raise_for_status()
        data = response.json()

    return (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )


def parse_plan_content(content: str) -> dict[str, Any]:
    raw = content.strip()
    candidates = build_parse_candidates(raw)

    parsed = None
    last_error = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            break
        except json.JSONDecodeError as error:
            last_error = error

    if parsed is None:
        snippet = raw[:600]
        raise ValueError(f"模型返回的内容不是有效 JSON：{last_error}. 原始片段：{snippet}")

    if not isinstance(parsed, dict):
        raise ValueError("Model response is not a JSON object")
    parsed.setdefault("summary", "AI 已生成整理建议。")
    parsed.setdefault("warnings", [])
    parsed.setdefault("actions", [])
    return parsed


def normalize_plan(plan: dict[str, Any], payload: BookmarkPlanRequest) -> dict[str, Any]:
    context = payload.context
    bookmark_map = {bookmark.id: bookmark for bookmark in context.bookmarks}
    folder_map = {folder.id: folder for folder in context.folders}
    existing_folder_paths = {tuple(folder.path) for folder in context.folders if folder.path}

    raw_actions = plan.get("actions", [])
    if not isinstance(raw_actions, list):
        raw_actions = []

    warnings = normalize_warnings(plan.get("warnings", []))
    normalized_actions, action_warnings = normalize_actions(
        raw_actions=raw_actions,
        bookmark_map=bookmark_map,
        folder_map=folder_map,
        existing_folder_paths=existing_folder_paths,
    )
    warnings.extend(action_warnings)
    warnings = normalize_warnings(warnings)

    summary = normalize_summary(plan.get("summary", ""), normalized_actions)
    return {
        "summary": summary,
        "warnings": warnings,
        "actions": normalized_actions,
    }


def normalize_summary(summary: Any, actions: list[dict[str, Any]]) -> str:
    if isinstance(summary, str):
        cleaned = re.sub(r"\s+", " ", summary).strip()
        if cleaned:
            return cleaned[:240]

    counts = {
        "create_folder": 0,
        "move_bookmark": 0,
        "rename_bookmark": 0,
        "rename_folder": 0,
    }
    for action in actions:
        action_type = action.get("type")
        if action_type in counts:
            counts[action_type] += 1

    parts: list[str] = []
    if counts["create_folder"]:
        parts.append(f"新增 {counts['create_folder']} 个文件夹")
    if counts["move_bookmark"]:
        parts.append(f"移动 {counts['move_bookmark']} 条书签")
    rename_count = counts["rename_bookmark"] + counts["rename_folder"]
    if rename_count:
        parts.append(f"统一 {rename_count} 个标题")

    if not parts:
        return "AI 已生成整理建议。"
    return "本次整理将" + "，".join(parts)


def normalize_warnings(warnings: Any) -> list[str]:
    if not isinstance(warnings, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in warnings:
        if not isinstance(item, str):
            continue
        cleaned = re.sub(r"\s+", " ", item).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned[:200])
    return result[:6]


def normalize_actions(
    *,
    raw_actions: list[Any],
    bookmark_map: dict[str, Any],
    folder_map: dict[str, Any],
    existing_folder_paths: set[tuple[str, ...]],
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    last_by_key: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}

    for index, raw_action in enumerate(raw_actions):
        if not isinstance(raw_action, dict):
            continue
        normalized = sanitize_action(raw_action)
        if not normalized:
            continue
        dedupe_key = build_action_dedupe_key(normalized)
        if dedupe_key is None:
            continue
        last_by_key[dedupe_key] = (index, normalized)

    ordered_actions = [item[1] for item in sorted(last_by_key.values(), key=lambda item: item[0])]

    created_paths = set(existing_folder_paths)
    create_actions: list[dict[str, Any]] = []
    non_create_actions: list[dict[str, Any]] = []
    seen_create_paths: set[tuple[str, ...]] = set()

    for action in ordered_actions:
        action_type = action["type"]
        if action_type == "create_folder":
            full_path = get_create_folder_full_path(action, folder_map)
            if not full_path or full_path in created_paths or full_path in seen_create_paths:
                continue
            if len(full_path) < 2:
                continue
            seen_create_paths.add(full_path)
            created_paths.add(full_path)
            create_actions.append(action)
            continue

        if action_type == "rename_bookmark":
            bookmark = bookmark_map.get(action.get("bookmarkId"))
            new_title = action.get("newTitle", "").strip()
            if not bookmark or not new_title or new_title == bookmark.title.strip():
                continue
            non_create_actions.append(action)
            continue

        if action_type == "rename_folder":
            folder = folder_map.get(action.get("folderId"))
            new_title = action.get("newTitle", "").strip()
            if not folder or not new_title or new_title == folder.title.strip():
                continue
            non_create_actions.append(action)
            continue

        if action_type == "move_bookmark":
            bookmark = bookmark_map.get(action.get("bookmarkId"))
            target_path = normalize_path(action.get("targetPath"))
            if not bookmark or not target_path:
                continue
            current_parent_path = tuple(bookmark.path[:-1]) if bookmark.path else tuple()
            if tuple(target_path) == current_parent_path:
                continue

            missing_paths = ensure_target_path_actions(
                target_path=tuple(target_path),
                created_paths=created_paths,
                existing_folder_paths=existing_folder_paths,
                seen_create_paths=seen_create_paths,
                create_actions=create_actions,
            )
            if missing_paths:
                warnings.append(f"已自动补齐 {len(missing_paths)} 个缺失目录步骤，以确保移动动作可执行。")
            non_create_actions.append(action)

    create_actions.sort(key=lambda action: len(get_create_folder_full_path(action, folder_map) or ()))
    final_actions = create_actions + non_create_actions
    final_actions = assign_action_ids(final_actions)

    if len(final_actions) > MAX_NORMALIZED_ACTIONS:
        final_actions = final_actions[:MAX_NORMALIZED_ACTIONS]
        warnings.append(f"动作过多，系统已收敛为前 {MAX_NORMALIZED_ACTIONS} 条必要动作。")

    return final_actions, warnings


def sanitize_action(action: dict[str, Any]) -> dict[str, Any] | None:
    action_type = action.get("type")
    if action_type not in {"create_folder", "move_bookmark", "rename_bookmark", "rename_folder"}:
        return None

    normalized: dict[str, Any] = {"type": action_type}
    if isinstance(action.get("actionId"), str) and action["actionId"].strip():
        normalized["actionId"] = action["actionId"].strip()

    for key in ("bookmarkId", "folderId", "targetFolderId", "parentId"):
        value = action.get(key)
        if isinstance(value, str) and value.strip():
            normalized[key] = value.strip()

    for key in ("title", "newTitle"):
        value = action.get(key)
        if isinstance(value, str):
            cleaned = re.sub(r"\s+", " ", value).strip()
            if cleaned:
                normalized[key] = cleaned[:120]

    parent_path = normalize_path(action.get("parentPath"))
    target_path = normalize_path(action.get("targetPath"))
    if parent_path:
        normalized["parentPath"] = parent_path
    if target_path:
        normalized["targetPath"] = target_path

    return normalized


def normalize_path(path: Any) -> list[str]:
    if not isinstance(path, list):
        return []
    result: list[str] = []
    for part in path:
        if not isinstance(part, str):
            continue
        cleaned = re.sub(r"\s+", " ", part).strip()
        if cleaned:
            result.append(cleaned[:80])
    return result


def build_action_dedupe_key(action: dict[str, Any]) -> tuple[str, str] | None:
    action_type = action["type"]
    if action_type == "create_folder":
        if "title" in action and "parentPath" in action:
            return action_type, json.dumps([action["parentPath"], action["title"]], ensure_ascii=False)
        return None
    if action_type == "move_bookmark":
        bookmark_id = action.get("bookmarkId")
        if not bookmark_id:
            return None
        return action_type, bookmark_id
    if action_type == "rename_bookmark":
        bookmark_id = action.get("bookmarkId")
        if not bookmark_id:
            return None
        return action_type, bookmark_id
    if action_type == "rename_folder":
        folder_id = action.get("folderId")
        if not folder_id:
            return None
        return action_type, folder_id
    return None


def get_create_folder_full_path(action: dict[str, Any], folder_map: dict[str, Any]) -> tuple[str, ...]:
    title = action.get("title")
    parent_path = action.get("parentPath")
    if isinstance(parent_path, list) and title:
        return tuple(parent_path + [title])
    parent_id = action.get("parentId")
    if parent_id and parent_id in folder_map and title:
        folder = folder_map[parent_id]
        return tuple(folder.path + [title])
    return tuple()


def ensure_target_path_actions(
    *,
    target_path: tuple[str, ...],
    created_paths: set[tuple[str, ...]],
    existing_folder_paths: set[tuple[str, ...]],
    seen_create_paths: set[tuple[str, ...]],
    create_actions: list[dict[str, Any]],
) -> list[tuple[str, ...]]:
    inserted: list[tuple[str, ...]] = []
    for index in range(1, len(target_path)):
        folder_path = target_path[: index + 1]
        parent_path = list(target_path[:index])
        title = target_path[index]
        if folder_path in created_paths or folder_path in existing_folder_paths or folder_path in seen_create_paths:
            created_paths.add(folder_path)
            continue
        create_actions.append(
            {
                "type": "create_folder",
                "title": title,
                "parentPath": parent_path,
            }
        )
        seen_create_paths.add(folder_path)
        created_paths.add(folder_path)
        inserted.append(folder_path)
    return inserted


def assign_action_ids(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assigned: list[dict[str, Any]] = []
    for index, action in enumerate(actions, start=1):
        updated = dict(action)
        updated["actionId"] = updated.get("actionId") or f"normalized-{index}"
        assigned.append(updated)
    return assigned


def build_parse_candidates(content: str) -> list[str]:
    candidates: list[str] = []
    queue = [content]

    if content.startswith("```"):
        fenced = strip_markdown_fence(content)
        queue.append(fenced)

    extracted = extract_first_json_object(content)
    if extracted:
        queue.append(extracted)

    normalized_inputs: list[str] = []
    for item in queue:
        normalized_inputs.append(item)
        normalized = normalize_json_like_text(item)
        if normalized != item:
            normalized_inputs.append(normalized)

    for item in normalized_inputs:
        if item and item not in candidates:
            candidates.append(item)

        extracted_item = extract_first_json_object(item)
        if extracted_item and extracted_item not in candidates:
            candidates.append(extracted_item)

        trimmed_item = trim_to_outer_json(item)
        if trimmed_item and trimmed_item not in candidates:
            candidates.append(trimmed_item)

    return candidates


def extract_first_json_object(content: str) -> str:
    start = content.find("{")
    if start == -1:
        return ""

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(content)):
        char = content[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start:index + 1]

    return ""


def strip_markdown_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def trim_to_outer_json(content: str) -> str:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return ""
    return content[start:end + 1].strip()


def normalize_json_like_text(content: str) -> str:
    normalized = content.strip()
    normalized = normalized.lstrip("\ufeff")
    normalized = normalized.replace("\u200b", "")
    normalized = normalized.replace("\u200c", "")
    normalized = normalized.replace("\u200d", "")
    normalized = normalized.replace("\xa0", " ")
    normalized = normalized.replace("“", '"')
    normalized = normalized.replace("”", '"')
    normalized = normalized.replace("‘", "'")
    normalized = normalized.replace("’", "'")
    normalized = normalized.replace("：", ":")
    normalized = normalized.replace("，", ",")
    normalized = normalized.replace("```json", "```")
    normalized = normalized.replace("```JSON", "```")
    normalized = remove_json_comments(normalized)
    normalized = re.sub(r",(\s*[}\]])", r"\1", normalized)
    normalized = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'\1"\2"\3', normalized)
    return normalized.strip()


def remove_json_comments(content: str) -> str:
    content = re.sub(r"^\s*//.*$", "", content, flags=re.MULTILINE)
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    return content


def build_fallback_plan(
    original_content: str,
    repaired_content: str,
    error: Exception,
) -> dict[str, Any]:
    original_snippet = compact_snippet(original_content)
    repaired_snippet = compact_snippet(repaired_content)
    logger.warning(
        "Falling back to empty plan after parse failure. original=%r repaired=%r error=%s",
        original_snippet,
        repaired_snippet,
        error,
    )
    return {
        "summary": "未能稳定生成整理方案，已返回空计划。",
        "warnings": [
            "模型返回了非标准 JSON，系统已自动降级为空动作结果。",
        ],
        "actions": [],
    }


def compact_snippet(content: str, limit: int = 300) -> str:
    collapsed = re.sub(r"\s+", " ", content).strip()
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit]}..."
