import os
import dashscope

dashscope.base_http_api_url = "your_api_url"

text = "通用多模态表征模型示例"
input = [{"text": text}]
resp = dashscope.MultiModalEmbedding.call(
    model="qwen3-vl-embedding",
    input=input,
    api_key='your_api_key'
)

print(resp)