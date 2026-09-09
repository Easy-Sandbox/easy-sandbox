# 👋 Welcome to Serverless Sandbox Community!

Hey everyone! Welcome to the **Serverless Sandbox** community — we're thrilled to have you here! 🎉

## What is Serverless Sandbox?

Serverless Sandbox is a Python SDK and CLI (`sbox`) for creating, managing, and interacting with cloud sandboxes designed for AI agents. It's E2B-protocol compatible with powerful extensions for the Alibaba Cloud ecosystem. Whether you're building autonomous agents, code interpreters, or secure execution environments, Serverless Sandbox gives you the tools to do it with zero-config simplicity.

## 🗂️ How to Use This Community

We want to keep things organized so everyone can find what they need:

| What you need | Where to go |
|---------------|-------------|
| 💡 **Feature Requests** | [Discussions → Ideas](https://github.com/Serverless-Sandbox/serverless-sandbox/discussions/categories/ideas) — suggest new features or improvements |
| 🐛 **Bug Reports** | [Issues](https://github.com/Serverless-Sandbox/serverless-sandbox/issues/new/choose) — report bugs using our issue templates |
| 💬 **Q&A / Help** | [Discussions → Q&A](https://github.com/Serverless-Sandbox/serverless-sandbox/discussions/categories/q-a) — ask questions and get help |
| 🎉 **Show and Tell** | [Discussions → Show and Tell](https://github.com/Serverless-Sandbox/serverless-sandbox/discussions/categories/show-and-tell) — share what you've built! |

## 🚀 Quick Start

```bash
pip install serverless-sandbox
```

```python
from serverless_sandbox import Sandbox

async def main():
    async with await Sandbox.create(template="python-base") as sb:
        result = await sb.run_code("print('Hello from sandbox!')")
        print(result.text)  # Hello from sandbox!
```

Or use the CLI:

```bash
pip install "serverless-sandbox[cli]"
sbox create --template python-base
sbox exec <sandbox-id> "echo hello"
```

## 📚 Key Links

- 📖 **[README & Docs](https://github.com/Serverless-Sandbox/serverless-sandbox#readme)**
- 🏗️ **[Design Document](https://github.com/Serverless-Sandbox/serverless-sandbox/blob/main/docs/DESIGN.md)**
- 📦 **[Community Templates](https://github.com/Serverless-Sandbox/awesome-templates)**
- 📝 **[Contributing Guide](https://github.com/Serverless-Sandbox/serverless-sandbox/blob/main/.github/CONTRIBUTING.md)**
- 🔒 **[Security Policy](https://github.com/Serverless-Sandbox/serverless-sandbox/blob/main/.github/SECURITY.md)**

## 🤝 Code of Conduct

We're committed to fostering a welcoming and inclusive environment. Please take a moment to review our [Code of Conduct](https://github.com/Serverless-Sandbox/serverless-sandbox/blob/main/.github/CODE_OF_CONDUCT.md). Be kind, be constructive, and help us build something great together.

---

We'd love to hear what you're building with Serverless Sandbox — feel free to introduce yourself and share your use case in the replies! 👇

Happy sandboxing! 🏖️
