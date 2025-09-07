# Leaflet AI Proxy

一个基于 FastAPI 的轻量级 OpenAI 兼容 API 代理服务，专为 [Leaflow 论坛分享的免费大模型 API](https://forum.leaflow.net/d/13-%E7%8E%B0%E5%9C%A8%E5%8F%AF%E4%BB%A5%E5%85%8D%E8%B4%B9%E4%BD%BF%E7%94%A8%E5%A4%A7%E6%A8%A1%E5%9E%8B-api) 设计。

## ✨ 特性

- 🔄 **OpenAI 兼容接口**：完全兼容 OpenAI API 规范
- 🚀 **高性能代理**：基于 httpx 和 HTTP/2，支持连接池和重试机制  
- 📡 **流式响应**：完整支持流式聊天补全
- 🔐 **灵活认证**：支持动态和静态 API 密钥
- 🌐 **CORS 支持**：内置跨域资源共享支持
- 📊 **健康检查**：提供服务健康状态监控
- 🐳 **Docker 就绪**：包含完整的容器化配置

## 🚀 快速开始

### 环境要求

- Python 3.13+
- 推荐使用 [uv](https://github.com/astral-sh/uv) 作为包管理器

### 安装依赖

```bash
# 使用 uv (推荐)
uv sync

# 或使用 pip
pip install -e .
```

### 环境配置

创建 `.env` 文件并配置必要的环境变量：

```env
# 上游 API 服务地址 (必需)
UPSTREAM_BASE_URL=http://your-upstream-api-url/v1

# 静态 API 密钥 (可选，作为默认密钥使用)
STATIC_API_KEY=your-api-key

# 可选配置项
CONNECT_TIMEOUT=5
READ_TIMEOUT=600
MAX_KEEPALIVE=100
MAX_CONNECTIONS=200
RETRY_TIMES=2
PORT=8080
```

### 运行服务

```bash
# 开发模式
python main.py

# 或使用 uvicorn
uvicorn main:app --host 0.0.0.0 --port 8080

# 使用 uv
uv run python main.py
```

### Docker 部署

```bash
# 构建镜像
docker build -t leaflet-ai .

# 运行容器
docker run -d \
  -p 8080:8080 \
  -e UPSTREAM_BASE_URL=http://your-upstream-api-url/v1 \
  -e STATIC_API_KEY=your-api-key \
  leaflet-ai
```

## 📖 API 使用

### 健康检查

```bash
curl http://localhost:8080/healthz
```

### 获取可用模型

```bash
curl -H "Authorization: Bearer your-token" \
     http://localhost:8080/v1/models
```

### 聊天补全（非流式）

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-token" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "user", "content": "你好"}
    ],
    "stream": false
  }'
```

### 聊天补全（流式）

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-token" \
  -d '{
    "model": "gpt-3.5-turbo", 
    "messages": [
      {"role": "user", "content": "讲个笑话"}
    ],
    "stream": true
  }' \
  --no-buffer
```

### 文本嵌入

```bash
curl -X POST http://localhost:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-token" \
  -d '{
    "input": ["Hello, world!"],
    "model": "text-embedding-ada-002"
  }'
```

## 🔧 配置说明

| 环境变量 | 必需 | 默认值 | 说明 |
|---------|------|--------|------|
| `UPSTREAM_BASE_URL` | ✅ | - | 上游 API 服务的基础 URL |
| `STATIC_API_KEY` | ❌ | - | 静态 API 密钥，当请求头无 Authorization 时使用 |
| `CONNECT_TIMEOUT` | ❌ | 5 | 连接超时时间（秒） |
| `READ_TIMEOUT` | ❌ | 600 | 读取超时时间（秒） |
| `MAX_KEEPALIVE` | ❌ | 100 | 最大保持活跃连接数 |
| `MAX_CONNECTIONS` | ❌ | 200 | 最大连接数 |
| `RETRY_TIMES` | ❌ | 2 | 请求重试次数 |
| `PORT` | ❌ | 8080 | 服务端口 |

## 🔐 认证机制

代理支持以下认证方式（按优先级排序）：

1. **请求头认证**：`Authorization: Bearer <token>` 
2. **环境变量认证**：使用 `STATIC_API_KEY`

支持的 token 格式：
- `your-token` → `your-token`
- `sk-your-token` → `your-token` (自动去除 sk- 前缀)
- `Bearer your-token` → `your-token` (自动去除 Bearer 前缀)

## 🧪 测试

```bash
# 运行所有测试
uv run pytest

# 运行测试并查看覆盖率
uv run pytest --cov=main
```

## 📁 项目结构

```
leaflet-ai/
├── main.py           # 主应用文件
├── pyproject.toml    # 项目配置和依赖
├── uv.lock          # 锁定的依赖版本
├── Dockerfile       # Docker 配置
├── test_main.http   # HTTP 测试文件
├── tests/           # 测试目录
│   ├── conftest.py  # 测试配置
│   └── test_api.py  # API 测试
└── README.md        # 项目说明
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

本项目采用 MIT 许可证。

## 🙏 致谢

感谢 [Leaflow 论坛](https://forum.leaflow.net/) 提供的免费大模型 API 资源。
