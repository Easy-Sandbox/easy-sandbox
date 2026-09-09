---
title: "Welcome to Serverless Sandbox Community!"
labels: []
---

👋 **Welcome to the Serverless Sandbox community!**

We're excited to have you here. Serverless Sandbox is a Python SDK and CLI (`sbox`) for creating, managing, and interacting with cloud sandboxes designed for AI agents — E2B-protocol compatible with extensions for the Alibaba Cloud ecosystem.

## 🗂️ Community Guide

Please use the right channel for your needs:

| Need | Where |
|------|-------|
| 💡 **Feature Request** | [Discussions → Ideas](https://github.com/Serverless-Sandbox/serverless-sandbox/discussions/categories/ideas) |
| 🐛 **Bug Report** | [Issues](https://github.com/Serverless-Sandbox/serverless-sandbox/issues/new/choose) |
| 💬 **Questions & Help** | [Discussions → Q&A](https://github.com/Serverless-Sandbox/serverless-sandbox/discussions/categories/q-a) |
| 🎉 **Show and Tell** | [Discussions → Show and Tell](https://github.com/Serverless-Sandbox/serverless-sandbox/discussions/categories/show-and-tell) |

## 🚀 Quick Start

```bash
pip install serverless-sandbox
```

```python
from serverless_sandbox import Sandbox

async def main():
    async with await Sandbox.create(template="python-base") as sb:
        result = await sb.run_code("print('Hello from sandbox!')")
        print(result.text)
```

## 📚 Resources

- 📖 [Documentation](https://github.com/Serverless-Sandbox/serverless-sandbox#readme)
- 🏗️ [Design Doc](https://github.com/Serverless-Sandbox/serverless-sandbox/blob/main/docs/DESIGN.md)
- 📦 [Community Templates](https://github.com/Serverless-Sandbox/awesome-templates)
- 📝 [Contributing Guide](https://github.com/Serverless-Sandbox/serverless-sandbox/blob/main/.github/CONTRIBUTING.md)

## 🤝 Code of Conduct

Please be respectful and constructive. We follow the [Contributor Covenant Code of Conduct](https://github.com/Serverless-Sandbox/serverless-sandbox/blob/main/.github/CODE_OF_CONDUCT.md).

---

Happy sandboxing! 🎉
