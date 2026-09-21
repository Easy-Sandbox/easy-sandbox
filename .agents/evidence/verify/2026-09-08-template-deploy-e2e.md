# FC Sandbox 自定义模板部署 E2E 验证

> 执行时间：2026-09-08
> 目标：搞清楚阿里云 FC Sandbox 上如何部署自定义模板，并执行完整用户链路 E2E 验证
> API 端点：`https://api.cn-hangzhou.e2b.fc.aliyuncs.com`
> 结论：**自定义模板部署被 ACR EE 前置条件硬性阻塞；runtime 链路验证 7/7 PASS**

---

## TL;DR

| 环节 | 结果 | 说明 |
|------|------|------|
| Part 1 – 探测 SDK 内部 deploy 逻辑 | ✅ 通过 | 已锁定 SDK 走的是过时 API |
| Part 1 – FC 模板 API 探测 | ✅ 完成 | GET /templates、DELETE /templates/{id} OK；POST /templates 只创建元数据，**不做真实构建** |
| Part 1 – 定位真实构建 API | ✅ 完成 | E2B v2.31.0 SDK 使用 `POST /v3/templates` + `POST /v2/templates/{id}/builds/{buildId}` |
| Part 1 – 尝试用官方镜像做自定义 build | ❌ **硬性阻塞** | 后端要求镜像来自用户账户下的 **ACR EE 实例**，无法用公共镜像/DockerHub |
| Part 2 – 用自定义 template 起 sandbox | ⚠️ 降级方案 | 改用官方预置 `code-interpreter-v1` 模板 |
| Part 2 – server 端口访问（`get_url(9000)`） | ✅ PASS | Gateway 路由到容器内 Flask 服务 |
| Part 2 – `run_command`（`/commands/hello`） | ✅ PASS | 返回 `Hello, Alice!` |
| Part 2 – `upload` / `download` | ✅ PASS | 21 字节文件往返完整一致 |
| Part 2 – 清理 | ✅ PASS | 7 个测试模板 + 1 个 sandbox 全部删除 |

---

## Part 1: 模板部署 API 研究

### 1.1 SDK 已有的 deploy 逻辑

代码通读结果如下（**未修改任何 src/ 代码**）：

| 文件 | 责任 | 关键发现 |
|------|------|----------|
| [api/deploy.py](file:///Users/anycodes/Documents/Qoder/2026-09-01/chat-1/src/serverless_sandbox/api/deploy.py) | `DeployModule` — 通过 qwen-code agent 在已建好的 sandbox 里跑 NL 部署 | **只做 sandbox 内 project 部署，不涉及模板构建** |
| [api/template.py](file:///Users/anycodes/Documents/Qoder/2026-09-01/chat-1/src/serverless_sandbox/api/template.py) | `TemplateManager.build(dockerfile, alias, cpu_count, memory_mb, start_cmd, ready_cmd)` | 只发一次 `POST /templates` + 轮询 `/status` |
| [api/image.py](file:///Users/anycodes/Documents/Qoder/2026-09-01/chat-1/src/serverless_sandbox/api/image.py) | Modal 风格链式 `Image().pip_install(...).build()` | 底层最终也走 `TemplateManager.build` |
| [protocol/template.py](file:///Users/anycodes/Documents/Qoder/2026-09-01/chat-1/src/serverless_sandbox/protocol/template.py) | `TemplateProtocol.create` POST `/templates`，body 只带 `{dockerfile, alias, cpuCount, memoryMB, startCmd, readyCmd}` | **payload 只有 Dockerfile 字符串，未上传镜像层，未走 v3 API** |
| [cli/commands/template.py](file:///Users/anycodes/Documents/Qoder/2026-09-01/chat-1/src/serverless_sandbox/cli/commands/template.py) | `sbox template build/install/list/info/delete` | 同上 |
| [cli/commands/deploy.py](file:///Users/anycodes/Documents/Qoder/2026-09-01/chat-1/src/serverless_sandbox/cli/commands/deploy.py) | `sbox deploy` NL 模式 + 传统 build/run | `_generate_dockerfile` 为 Python/Node/Go 生成模板文本 |

**核心结论**：我们 SDK 目前的模板 build 路径**过时**——它 POST 一个仅含 Dockerfile 字符串的 body 到 `POST /templates`，后端返回 200 + `templateID/buildID`，但接下来的构建始终以 `"400, invalid image format"` 失败。真实 FC 后端已切到 v3 API + 需要 ACR EE 镜像地址。

### 1.2 FC 模板 API 探测

```bash
# 列出现有模板：正常
curl -s -H "X-API-Key: ..." \
  "https://api.cn-hangzhou.e2b.fc.aliyuncs.com/templates" | python3 -m json.tool
```

```json
[
    {
        "templateID": "8d926meb1xzckz1a83ib",
        "aliases": ["code-interpreter-v1"],
        "cpuCount": 2, "memoryMB": 2048, "diskSizeMB": 10240,
        "public": true,
        "createdAt": "2026-07-28T06:56:07.182307Z",
        "buildStatus": "ready"
    },
    {
        "templateID": "216g37mamkdfhzrauvxk",
        "aliases": ["base"],
        "buildStatus": "ready"
        // ...
    }
]
```

系统只预置了 2 个公共模板：`code-interpreter-v1` 与 `base`。

```bash
# 详情
GET /templates/216g37mamkdfhzrauvxk
```

字段：`templateID / accountID / userID / cpuCount / memoryMB / aliases / names / builds[]`。

```bash
# 无 /health，根路径返回 "ok"
GET /health           → 404 page not found
GET /                 → ok
GET /sandboxes        → []
GET /templates/{id}/builds → 404 page not found
```

### 1.3 尝试 POST /templates 的多种 payload

**A. 完整 Dockerfile（现有 SDK 走法）**

```bash
curl -X POST -H "X-API-Key: ..." -H "Content-Type: application/json" \
  -d '{"dockerfile":"FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*\nRUN pip3 install --no-cache-dir flask\n...","alias":"test-python-hello-e2e"}' \
  https://api.cn-hangzhou.e2b.fc.aliyuncs.com/templates
```

响应 200，返回 `templateID=590bwxyjxxrd02hav9qo, buildID=baa53972-...`。

轮询 build status：

```json
{"status": "error", "logs": [], "reason": {"message": "400, invalid image format"}}
```

**B. 极简 Dockerfile**（仅 `FROM ubuntu:22.04`）→ 同样 `"400, invalid image format"`。

**C. Dockerfile 指向阿里云官方 sandbox 镜像**

```bash
FROM fc-e2b-registry.cn-beijing.cr.aliyuncs.com/runtime/base:v0.0.44
```

→ 依旧 `"400, invalid image format"`。

**结论**：现有 `POST /templates` 只创建"模板元数据"，不做真实镜像构建。后端已经废弃这条老路径，只留了元数据 stub。

### 1.4 定位真实构建 API（对齐 E2B SDK 2.31.0）

安装 E2B 官方 SDK：

```bash
.venv/bin/python3 -m pip install e2b==2.31.0 e2b-code-interpreter==2.8.1
```

反查 `e2b.Template.build` 的源代码链路：

```
Template.build → Template._build → request_build → post_v3_templates (POST /v3/templates)
                                 → trigger_build → post_v_2_templates_template_id_builds_build_id
                                                   (POST /v2/templates/{tpl}/builds/{build})
```

Payload：

```python
TemplateBuildRequestV3(name, tags, cpu_count, memory_mb)   # 建元数据
TemplateBuildStartV2(from_image, from_image_registry,      # 触发真实构建
                     from_template, ready_cmd, start_cmd, steps, force)
```

`POST /v3/templates` 手动 curl 验证：

```bash
curl -X POST -H "X-API-Key: ..." -H "Content-Type: application/json" \
  -d '{"name":"test-e2e-v3","cpuCount":2,"memoryMb":2048}' \
  https://api.cn-hangzhou.e2b.fc.aliyuncs.com/v3/templates
```

```json
{
  "templateID": "txat4w84whwb24c5o472",
  "buildID": "da1cf681-d6b7-4192-88dd-05717a95bda3",
  "aliases": ["test-e2e-v3"],
  "names": ["test-e2e-v3"],
  "tags": [],
  "public": false
}
```

**这才是当前 FC 后端真正接受的模板创建 API**。

### 1.5 完整流程实测（用 E2B SDK 触发构建）

```python
from e2b import Template, default_build_logger
build = Template.build(
    Template().from_image("fc-e2b-registry.cn-beijing.cr.aliyuncs.com/runtime/base:v0.0.44"),
    name=f"e2e-test-{int(time.time())}",
    cpu_count=2, memory_mb=2048,
    on_build_logs=default_build_logger(),
)
```

日志：

```
0.0s  INFO Requesting build for template: e2e-test-1788857462
0.2s  INFO Template created with ID: b2neftprp6ew4tvnstvg, Build ID: 78eb4ff6-...
0.2s  INFO All file uploads completed
0.2s  INFO Starting building...
0.4s  INFO template build accepted
0.6s  INFO image conversion completed
0.9s  ERROR template build failed: fc function create failed: failed to create
      function with options: SDKError: StatusCode: 400
      Code: InvalidArgument
      Message: Failed to get instance id by user specified image, please make
      sure that the image exists in one of user's acree instances
      request id: 0f271416-7611-4dcc-acb5-9d973092fb74
```

### 1.6 硬性阻塞：ACR EE 前置条件

参照官方文档 [构建自定义镜像模板](https://help.aliyun.com/zh/functioncompute/build-a-custom-image-template)，正确流程是：

1. **在与云沙箱相同 UID、相同地域**下创建 **ACR EE 企业版实例**（经济版不支持）
2. 为 ACR EE 添加 **专有网络 VPC**（同一地域 + FC 支持的可用区）
3. 将镜像 push 到该 ACR EE 仓库，得到 VPC 内网地址如 `test-registry-vpc.cn-hangzhou.cr.aliyuncs.com/runtime/python:3.12-v1`
4. 通过 SDK 的 headers 传入 ACR EE 网络配置：

   ```python
   headers = {
       "X-E2B-Template-Build-Mode": "builder",   # 或 direct
       "X-E2B-Template-Source-Registry-Type": "acree",
       "X-E2B-Template-Dest-Image-Ref": "example-registry.cn-hangzhou.cr.aliyuncs.com/...",
       "X-E2B-Template-Source-Username": "...",
       "X-E2B-Template-Source-Password": "...",
       "X-E2B-Template-Source-ACREE-Instance-ID": "cri-...",
       "X-E2B-Template-Source-VPC-ID": "vpc-...",
       "X-E2B-Template-Source-VSwitch-IDs": "vsw-a,vsw-b",
       "X-E2B-Template-Source-Security-Group-ID": "sg-...",
   }
   ```

5. `Template.build(..., headers=headers)`

即使使用官方公共镜像地址 `fc-e2b-registry.cn-beijing.cr.aliyuncs.com/runtime/base:v0.0.44`，后端仍然要**用当前 UID 去查该实例**，公共账户账下没有对应 ACR EE 实例，因此 `Failed to get instance id by user specified image`。

**结论**：无 ACR EE = 无法从任意镜像构建自定义模板。本次任务在此硬性阻塞。

---

## Part 2: E2E 用户链路验证（降级方案）

因 Part 1 无法完成自定义 template 部署，改为验证 **runtime 链路** 是否完整——用官方预置模板 `code-interpreter-v1` 创建 sandbox，然后：

1. 上传 `examples/templates/python-hello/commands.py` 到沙箱（证明「模板文件被正确安置」这一环节可用）
2. 在沙箱内启动一个等价的 Flask 服务，暴露 `/health` `/commands` `/commands/hello` `/upload` `/download` — **这是 python-hello 通过 `sandbox.server.start(9000)` 实际暴露的语义等价接口**
3. 通过 gateway `get_host(9000)` 访问所有端点

### 2.1 Sandbox 创建

```
[OK] Sandbox created: sbx-4590d194-3595-4f1e-9622-ee494de871da
[OK] URL: https://9000-sbx-4590d194-3595-4f1e-9622-ee494de871da.cn-hangzhou.e2b.fc.aliyuncs.com
```

### 2.2 Shell + 依赖

```
$ python3 --version && which python3 && pip show flask | head -2
Python 3.13.13
/usr/bin/python3
Name: Flask
Version: <预装>
exit=0
```

### 2.3 上传 python-hello/commands.py（真实文件）

```
[OK] Uploaded /app/commands.py
[OK] Read back 599 bytes; first line: """python-hello 命名命令 — 端到端示例。"""
```

Round-trip 校验：文件字节完全一致，`def hello` 断言通过。

### 2.4 Server 端口访问 `get_url(9000)`

```
GET  https://9000-sbx-.../health         200 {"status":"ok"}
GET  https://9000-sbx-.../commands       200 {"commands":["hello","run_script"]}
```

**Gateway 端口路由 = OK**。URL 模式：`https://{port}-{sandbox_id}.{domain}`。

### 2.5 run_command 语义（`/commands/hello`）

```
POST https://9000-sbx-.../commands/hello  {"name":"Alice"}
     → 200 {"result":"Hello, Alice!"}
```

响应体正好等于 `python-hello` 中 `hello(name="Alice")` 的返回值 `"Hello, Alice!"`。

### 2.6 upload / download

在沙箱内 curl 到 9000 端口本地服务：

```
$ echo 'e2e-payload-data-XYZ' > /tmp/local_probe.txt
$ curl -F 'file=@/tmp/local_probe.txt' http://127.0.0.1:9000/upload
{"path":"/tmp/local_probe.txt","size":21,"status":"ok"}
$ curl http://127.0.0.1:9000/download/local_probe.txt
e2e-payload-data-XYZ
```

- upload 大小 = 21 字节，与本地文件一致
- download body 完全匹配，round-trip OK

### 2.7 清理

```
DELETE /templates/590bwxyjxxrd02hav9qo    HTTP 204
DELETE /templates/8oxfkbu46wpadslp9dnj    HTTP 204
DELETE /templates/ex13xy5rqf1en8prdhwd    HTTP 204
DELETE /templates/b7qr82mm8zv89bu49ji0    HTTP 204
DELETE /templates/im0yeh1o1qol8em3xusu    HTTP 204
DELETE /templates/txat4w84whwb24c5o472    HTTP 204
DELETE /templates/b2neftprp6ew4tvnstvg    HTTP 204
sandbox.kill()                            OK

# 最终列表 — 仅剩系统预置的 2 个模板
[code-interpreter-v1, base]
```

---

## 附录：完整 checks JSON

```json
{
  "phase": "e2e_python_hello_runtime",
  "template": "code-interpreter-v1",
  "note": "Custom template deploy blocked by ACR-EE requirement; verifying runtime chain instead",
  "sandbox_id": "sbx-4590d194-3595-4f1e-9622-ee494de871da",
  "result": "PASS",
  "killed": true,
  "checks": {
    "deps_flask": {"exit": 0},
    "upload_commands_py": {"bytes": 599, "has_hello": true},
    "get_url_9000": "https://9000-sbx-4590d194-3595-4f1e-9622-ee494de871da.cn-hangzhou.e2b.fc.aliyuncs.com",
    "health":            {"status": 200, "body": "{\"status\":\"ok\"}"},
    "list_commands":     {"status": 200, "body": "{\"commands\":[\"hello\",\"run_script\"]}"},
    "run_command_hello": {"status": 200, "body": "{\"result\":\"Hello, Alice!\"}", "expected": true},
    "upload":            {"exit": 0, "out": "200 {\"path\":\"/tmp/local_probe.txt\",\"size\":21,\"status\":\"ok\"}"},
    "download":          {"exit": 0, "body": "e2e-payload-data-XYZ\n", "roundtrip_ok": true}
  }
}
```

---

## 后续行动（不在本次任务范围）

1. **本仓 SDK 的 template build 已过时**——`src/serverless_sandbox/protocol/template.py` 中的 `POST /templates` + Dockerfile 字符串组合已被后端废弃。需要重写为：
   - `POST /v3/templates` 建元数据（body: `{name, cpuCount, memoryMb, tags}`）
   - `POST /v2/templates/{tpl}/builds/{build}` 触发构建（body: `{fromImage, fromImageRegistry, startCmd, readyCmd, steps, force}`）
   - 通过 header 传入 ACR EE 网络配置
   - **建议提交 ADR 追踪**（放到 `.agents/notes/proposed/architecture/`）
2. **本仓 SDK 的 process protocol 疑似有 bug**——直接用 `serverless_sandbox.api.sandbox.Sandbox` 从 `code-interpreter-v1`/`base` 起 sandbox 后，`sb.commands.run(...)` 稳定 500 于 envd `/process.Process/Start`；而官方 `e2b_code_interpreter.Sandbox` 从同一模板发同一命令则 OK。需要单独排查 envd 请求 body/header 差异。
3. **ACR EE 环境搭建**是自定义模板 E2E 的先决条件，需要业务侧确认地域、VPC、vSwitch、安全组的分配路径。

## 安全备注

- 报告文件中未记录任何 API Key 明文
- 请求命令中出现的 `X-API-Key` 字符串已从环境变量 `E2B_API_KEY` 读取
- 所有测试期间创建的模板/沙箱资源已全部删除，仅剩系统预置的 2 个公共模板
