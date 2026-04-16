# Bilibili RAG 多Agent协作系统

基于用户B站收藏夹，构建智能推荐和知识检索系统。通过多Agent协作，实现视频内容理解、语义搜索、个性化推荐等功能。

## 功能特性

### 核心功能
- **B站扫码登录** - 安全便捷的登录方式
- **智能收藏夹管理** - 自动整理和分类收藏内容
- **AI内容提取** - 自动生成视频摘要和要点
- **语义搜索** - 基于向量数据库的自然语言搜索
- **对话式问答** - 针对收藏内容的智能问答
- **用户画像分析** - 基于兴趣标签和行为的多维画像
- **个性化推荐** - 结合LLM重排的视频推荐系统

### 技术特点
- **多Agent架构** - Supervisor模式协调多个专业Agent
- **向量检索** - 基于ChromaDB的语义检索
- **多模态分析** - 视频封面理解和内容分析
- **实时同步** - 支持收藏夹、追番、影视等多数据源
- **WebSocket推送** - 实时推荐和通知

## 系统架构

### 后端技术栈
- **FastAPI** - 高性能Web框架
- **SQLAlchemy** - ORM和数据库管理
- **ChromaDB** - 向量数据库
- **LangChain/LangGraph** - LLM应用框架
- **DashScope** - 阿里云大模型API
- **DeerFlow** - Agent框架

### 前端技术栈
- **Next.js 16** - React框架
- **TypeScript** - 类型安全
- **Tailwind CSS** - 样式框架
- **WebSocket** - 实时通信

## 快速开始

### 环境要求
- Python 3.11+
- Node.js 18+
- Conda (推荐)

### 安装步骤

1. **克隆项目**
```bash
git clone <your-repo-url>
cd bilibili-rag-main
```

2. **创建Python环境**
```bash
conda create -n bilibili python=3.11
conda activate bilibili
```

3. **安装后端依赖**
```bash
pip install -r requirements.txt
pip install -e ./backend/packages/harness
```

4. **配置环境变量**
```bash
cp .env.example .env
# 编辑 .env 文件，填入必要的API密钥
```

5. **安装前端依赖**
```bash
cd frontend
npm install
```

### 启动服务

1. **启动后端**
```bash
# 在项目根目录
conda activate bilibili
E:\anaconda\envs\bilibili\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

2. **启动前端**
```bash
# 在 frontend 目录
npm run dev
```

3. **访问应用**
打开浏览器访问 `http://localhost:3000`

## 配置说明

### 环境变量 (.env)
```bash
# 大模型配置
DASHSCOPE_API_KEY=your_dashscope_api_key
OPENAI_API_KEY=your_openai_api_key
LLM_MODEL=
OPENAI_BASE_URL=[image_uploaded] 数据库配置（可选）
DATABASE_URL=sqlite+aiosqlite:///./data/bilibili_rag.db
```

### 配置文件 (config.yaml)
主要包含：
- 模型配置
- 工具注册
- Agent配置
- 技能配置
- 记忆系统配置

## 项目结构

```
bilibili-rag-main/
├── app/                    # 后端核心代码
│   ├── agents/            # Agent实现
│   ├── routers/           # API路由
│   ├── services/          # 业务逻辑
│   ├── models/            # 数据模型
│   └── tools/             # 工具函数
├── frontend/              # 前端代码
│   ├── app/               # Next.js应用
│   ├── components/        # React组件
│   └── lib/               # 工具库
├── backend/               # DeerFlow框架
│   └── packages/harness/  # Agent框架
├── scripts/               # 工具脚本
├── skills/                # Agent技能
├── docs/                  # 文档
├── data/                  # 数据文件
└── logs/                  # 日志文件
```

## 核心模块

### 推荐系统
- **候选召回** - 多路召回策略（兴趣、分区、UP主、热榜）
- **LLM重排** - 基于用户画像的智能排序
- **理由生成** - 个性化推荐理由
- **画像构建** - 多数据源用户画像

### 检索系统
- **向量检索** - 基于ChromaDB的语义搜索
- **关键词检索** - 传统关键词匹配
- **混合检索** - 向量和关键词结合

### 用户画像
- **兴趣标签** - 基于收藏内容的兴趣提取
- **行为分析** - 观看历史和收藏行为
- **多源整合** - 收藏、追番、影视等数据源

## API文档

启动后端后访问 `http://localhost:8000/docs` 查看完整API文档。

## 开发指南

### 添加新的Agent
1. 在 `app/agents/` 创建Agent文件
2. 在 `app/services/tools/registry.py` 注册工具
3. 在 `app/main.py` 初始化Agent

### 添加新的工具
1. 在 `app/services/tools/` 创建工具文件
2. 使用 `@tool` 装饰器定义工具
3. 在 `app/services/tools/registry.py` 注册

## 常见问题

### Q: DeerFlow客户端初始化失败？
A: 确保使用bilibili环境的Python启动后端：
```bash
E:\anaconda\envs\bilibili\python.exe -m uvicorn app.main:app
```

### Q: 前端无法连接后端？
A: 检查后端是否启动在8000端口，前端API配置是否正确。

### Q: 向量检索没有结果？
A: 确保已同步收藏夹内容，向量数据库已初始化。

## 贡献指南

欢迎提交Issue和Pull Request。在提交PR前请确保：
1. 代码通过风格检查
2. 添加必要的测试
3. 更新相关文档

## 许可证

MIT License

## 致谢

- B站API - 提供数据接口
- 阿里云DashScope - 提供大模型服务
- via007/bilibili-rag - 提供灵感