"""Unit tests for mugen.core.gateway.completion.bedrock.BedrockCompletionGateway."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core.gateway.completion.bedrock import BedrockCompletionGateway


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        aws=SimpleNamespace(
            bedrock=SimpleNamespace(
                api=SimpleNamespace(
                    region="us-east-1",
                    access_key_id="AKIA_TEST",
                    secret_access_key="SECRET_TEST",
                    dict={
                        "completion": {
                            "model": "anthropic.claude",
                            "max_tokens": "128",
                            "temp": "0.7",
                            "top_p": "0.9",
                        },
                    },
                )
            )
        )
    )


class TestMugenGatewayCompletionBedrock(unittest.IsolatedAsyncioTestCase):
    """Covers request shaping and failure handling for Bedrock completion."""

    async def test_get_completion_builds_messages_and_returns_trimmed_content(
        self,
    ) -> None:
        config = _make_config()
        logging_gateway = Mock()
        bedrock_client = Mock()
        bedrock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": "  hello world  ",
                        }
                    ]
                }
            }
        }

        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=bedrock_client,
        ) as boto_client:
            gateway = BedrockCompletionGateway(config, logging_gateway)

        boto_client.assert_called_once_with(
            service_name="bedrock-runtime",
            region_name="us-east-1",
            aws_access_key_id="AKIA_TEST",
            aws_secret_access_key="SECRET_TEST",
        )

        response = await gateway.get_completion(
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ]
        )

        self.assertIsNotNone(response)
        self.assertEqual(response.content, "hello world")
        bedrock_client.converse.assert_called_once_with(
            modelId="anthropic.claude",
            messages=[
                {"role": "user", "content": [{"text": "hello"}]},
                {"role": "assistant", "content": [{"text": "hi"}]},
            ],
            system=[{"text": "sys"}],
            inferenceConfig={
                "maxTokens": 128,
                "temperature": 0.7,
                "topP": 0.9,
            },
        )

    async def test_get_completion_returns_none_on_exception(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        bedrock_client = Mock()
        bedrock_client.converse.side_effect = RuntimeError("boom")

        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=bedrock_client,
        ):
            gateway = BedrockCompletionGateway(config, logging_gateway)

        with patch(
            "mugen.core.gateway.completion.bedrock.traceback.print_exc"
        ) as print_exc:
            response = await gateway.get_completion(
                [{"role": "user", "content": "hello"}]
            )

        self.assertIsNone(response)
        print_exc.assert_called_once()
