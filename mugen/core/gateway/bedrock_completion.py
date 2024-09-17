"""Provides an AWS Bedrock chat completion gateway."""

# https://aws.amazon.com/bedrock/

import traceback
from types import SimpleNamespace

import boto3
from botocore.exceptions import ClientError

from mugen.core.contract.completion_gateway import ICompletionGateway
from mugen.core.contract.logging_gateway import ILoggingGateway


# pylint: disable=too-few-public-methods
class BedrockCompletionGateway(ICompletionGateway):
    """An AWS Bedrock chat compeltion gateway."""

    _env_prefix = "bedrock"

    def __init__(
        self,
        config: dict,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = SimpleNamespace(**config)
        self._logging_gateway = logging_gateway

        self._client = boto3.client(
            service_name="bedrock-runtime",
            region_name=self._config.bedrock_api_region,
            aws_access_key_id=self._config.bedrock_api_access_key_id,
            aws_secret_access_key=self._config.bedrock_api_secret_access_key,
        )

    async def get_completion(
        self,
        context: list[dict],
        operation: str = "completion",
    ) -> SimpleNamespace | None:
        model = self._config.__dict__[f"{self._env_prefix}_api_{operation}_model"]
        temperature = float(
            self._config.__dict__[f"{self._env_prefix}_api_{operation}_temp"]
        )

        response = None
        conversation = []
        system_prompts = []
        for msg in context:
            if msg["role"] in ["user", "assistant"]:
                conversation.append(
                    {"role": msg["role"], "content": [{"text": msg["content"]}]}
                )
            else:
                system_prompts.append({"text": msg["content"]})
        try:
            completion = self._client.converse(
                modelId=model,
                messages=conversation,
                system=system_prompts,
                inferenceConfig={
                    "maxTokens": 512,
                    "temperature": temperature,
                    "topP": 0.9,
                },
            )
            response = SimpleNamespace()
            response.content = completion["output"]["message"]["content"][0][
                "text"
            ].strip()
        # pylint: disable=broad-exception-caught
        except (ClientError, Exception):
            traceback.print_exc()

        return response
