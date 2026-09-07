"""
bot factory

CowAgent-Rev keeps only two model backends:
  - the OpenAI-compatible aggregator (OneAPI / NewAPI / any OpenAI-style endpoint,
    including Azure and custom providers), and
  - the Zhipu AI (GLM) native SDK.
"""
from common import const


def create_bot(bot_type):
    """
    create a bot_type instance
    :param bot_type: bot type code
    :return: bot instance
    """
    if bot_type in (const.OPENAI, const.CHATGPT, const.CUSTOM) or bot_type.startswith("custom:"):  # OpenAI-compatible API
        from models.chatgpt.chat_gpt_bot import ChatGPTBot
        return ChatGPTBot()

    elif bot_type == const.OPEN_AI:
        # OpenAI official chat API
        from models.openai.open_ai_bot import OpenAIBot
        return OpenAIBot()

    elif bot_type == const.CHATGPTONAZURE:
        # Azure OpenAI service https://azure.microsoft.com/products/ai-services/openai-service
        from models.chatgpt.chat_gpt_bot import AzureChatGPTBot
        return AzureChatGPTBot()

    elif bot_type == const.ZHIPU_AI or bot_type == "glm-4":  # "glm-4" kept for backward compatibility
        from models.zhipuai.zhipuai_bot import ZHIPUAIBot
        return ZHIPUAIBot()

    raise RuntimeError(f"unsupported bot_type: {bot_type!r}")
