import unittest
from types import SimpleNamespace
from unittest import mock

from app import ai_service
from app.schemas import BookmarkContext, BookmarkPlanRequest


class FakeResponse:
    def __init__(self, content: str) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": self._content,
                    }
                }
            ]
        }


class FakeAsyncClient:
    def __init__(self, responses: list[FakeResponse], *args, **kwargs) -> None:
        self._responses = responses

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, *args, **kwargs) -> FakeResponse:
        return self._responses.pop(0)


class ParsePlanContentTests(unittest.TestCase):
    def test_parse_plan_content_accepts_normalized_json_like_text(self) -> None:
        content = """
        ```json
        {
          summary: "整理建议",
          warnings: [],
          actions: [
            {
              actionId: "a1",
              type: "rename_bookmark",
              bookmarkId: "42",
              newTitle: "Google"
            },
          ],
        }
        ```
        """

        parsed = ai_service.parse_plan_content(content)

        self.assertEqual(parsed["summary"], "整理建议")
        self.assertEqual(parsed["actions"][0]["bookmarkId"], "42")
        self.assertEqual(parsed["actions"][0]["newTitle"], "Google")

    def test_build_fallback_plan_returns_empty_actions(self) -> None:
        plan = ai_service.build_fallback_plan(
            original_content="{broken",
            repaired_content="{still broken",
            error=ValueError("bad json"),
        )

        self.assertEqual(plan["actions"], [])
        self.assertTrue(plan["warnings"])


class GeneratePlanFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_plan_returns_empty_plan_when_model_output_is_unparseable(self) -> None:
        payload = BookmarkPlanRequest(
            requestId="req-1",
            instruction="帮我整理一下",
            context=BookmarkContext(),
        )
        responses = [
            FakeResponse('{"summary" "missing colon"}'),
            FakeResponse('{"actions"[}'),
        ]

        with mock.patch.object(
            ai_service,
            "settings",
            SimpleNamespace(
                api_base="https://example.test",
                api_key="test-key",
                model="test-model",
            ),
        ), mock.patch.object(
            ai_service.httpx,
            "AsyncClient",
            side_effect=lambda *args, **kwargs: FakeAsyncClient(responses, *args, **kwargs),
        ):
            result = await ai_service.generate_plan(payload)

        self.assertEqual(result.actions, [])
        self.assertEqual(
            result.warnings,
            ["模型返回了非标准 JSON，系统已自动降级为空动作结果。"],
        )
        self.assertEqual(result.summary, "未能稳定生成整理方案，已返回空计划。")


if __name__ == "__main__":
    unittest.main()
