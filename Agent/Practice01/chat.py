import configparser
import os
from openai import OpenAI

config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), "config.ini"), encoding="utf-8")

client = OpenAI(
    api_key=config["llm"]["api_key"],
    base_url=config["llm"]["base_url"],
)

messages = []

while True:
    question = input("请输入你的问题：")
    messages.append({"role": "user", "content": question})

    stream = client.chat.completions.create(
        model=config["llm"]["model"],
        messages=messages,
        stream=True,
    )

    reply = ""
    for chunk in stream:
        if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
            reply += chunk.choices[0].delta.content

    print()
    messages.append({"role": "assistant", "content": reply})
