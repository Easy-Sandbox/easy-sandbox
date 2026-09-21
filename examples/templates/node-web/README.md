# Node.js Web 服务模板

Node.js 20 Web 服务沙箱环境，适用于 Express、Fastify、Koa 等框架的快速开发与部署。

## 环境说明

| 类别 | 内容 |
|------|------|
| **基础镜像** | node:20-slim |
| **Node.js** | Node.js 20.x + npm |
| **全局工具** | yarn、nodemon、pm2 |
| **系统工具** | curl、wget、git、jq |
| **资源配置** | 1 CPU / 2048 MB 内存 |
| **暴露端口** | 3000 |

## 安装方式

**从本地安装：**

```bash
ebx install ./examples/templates/node-web --registry-type local
```

**从 GitHub 安装：**

```bash
ebx install Easy-Sandbox/awesome-templates//node-web
```

## 使用示例

创建沙箱实例：

```bash
ebx create --template node-web
```

在沙箱中初始化 Express 项目并启动：

```bash
ebx exec <sandbox-id> -- bash -c "
cd /workspace && \
npm init -y && \
npm install express && \
cat > index.js << 'EOF'
const express = require('express');
const app = express();
const port = process.env.PORT || 3000;

app.get('/', (req, res) => {
  res.json({ message: 'Hello from Easy Sandbox!' });
});

app.listen(port, () => {
  console.log('Server running on port ' + port);
});
EOF
node index.js
"
```

使用 Python SDK：

```python
from easy_sandbox import Sandbox

sandbox = Sandbox.create(template="node-web")

# 写入服务器代码
sandbox.files.write("/workspace/index.js", """
const http = require('http');
const server = http.createServer((req, res) => {
    res.writeHead(200, {'Content-Type': 'application/json'});
    res.end(JSON.stringify({status: 'ok'}));
});
server.listen(3000);
""")

# 启动服务
sandbox.commands.run("node /workspace/index.js &")

# 测试访问
result = sandbox.commands.run("curl -s http://localhost:3000")
print(result.stdout)
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `NODE_ENV` | Node.js 运行环境 | `production` |
| `PORT` | Web 服务监听端口 | `3000` |

### 使用 pm2 管理进程

pm2 已预装，可用于进程管理：

```bash
# 启动服务
pm2 start index.js --name my-app

# 查看状态
pm2 status

# 查看日志
pm2 logs my-app
```

### 使用 nodemon 开发模式

开发阶段可使用 nodemon 实现热重载：

```bash
NODE_ENV=development nodemon index.js
```

## 注意事项

- **端口映射**：默认暴露 3000 端口，如需其他端口，请在创建沙箱时通过配置指定。
- **生产环境**：`NODE_ENV` 默认为 `production`，开发时可设为 `development` 以获取详细错误信息。
- **包管理器**：npm 和 yarn 均已安装，根据项目需要选择使用。
- **进程管理**：生产环境建议使用 pm2 管理 Node.js 进程，确保服务稳定运行。
