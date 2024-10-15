"""Provides an AWS Bedrock chat completion gateway."""

# https://aws.amazon.com/bedrock/

import traceback
from types import SimpleNamespace

import boto3
from botocore.exceptions import ClientError

from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.logging import ILoggingGateway


# pylint: disable=too-few-public-methods
class BedrockCompletionGateway(ICompletionGateway):
    """An AWS Bedrock chat compeltion gateway."""

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._logging_gateway = logging_gateway

        self._client = boto3.client(
            service_name="bedrock-runtime",
            region_name=self._config.aws.bedrock.api.region,
            aws_access_key_id=self._config.aws.bedrock.api.access_key_id,
            aws_secret_access_key=self._config.aws.bedrock.api.secret_access_key,
        )

    async def get_completion(
        self,
        context: list[dict],
        operation: str = "completion",
    ) -> SimpleNamespace | None:
        model = self._config.aws.bedrock.api.dict[operation]["model"]
        temperature = float(self._config.aws.bedrock.api.dict[operation]["temp"])

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
