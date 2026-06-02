# Error Analysis Service

AI 驱动的代码错误分析微服务，为智能实验辅助系统（PTA 教学辅助平台）提供错误诊断、学习预警和实验分析能力。

## 快速启动

```bash
# 1. 安装依赖
uv sync

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY

# 3. 启动服务
uv run uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

启动后可访问：
- 健康检查：`GET http://127.0.0.1:8002/health`
- Swagger 文档：`http://127.0.0.1:8002/docs`

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | - | DeepSeek API Key（**必填**） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名称 |
| `SERVICE_HOST` | `0.0.0.0` | 监听地址 |
| `SERVICE_PORT` | `8002` | 服务端口 |
| `REQUEST_TIMEOUT` | `30` | DeepSeek 请求超时(秒) |
| `MAX_CODE_LINES` | `3000` | 单次分析最大代码行数 |

## API 接口

所有接口返回统一格式：`{"code": 200, "message": "success", "data": {...}}`

### 1. POST `/ai/error/analyze` — AI 错误分析

分析学生代码提交历史，诊断错误根因，生成学习建议。

**请求示例：**
```json
{
  "studentId": "20220101001",
  "studentName": "张三",
  "experimentId": 42,
  "experimentName": "实验三-链表",
  "problemTitle": "链表反转",
  "problemDescription": "给定一个单链表的头节点 head，请反转链表...",
  "submissions": [
    {
      "attemptNo": 1,
      "judgeStatus": "COMPILE_ERROR",
      "compiler": "GCC",
      "errorMessage": "error: 'ListNode' was not declared in this scope",
      "code": "#include <stdio.h>\nListNode* reverseList(ListNode* head) {...}",
      "runtimeMs": null,
      "memoryKb": null,
      "submittedAt": "2026-06-03T10:30:00"
    }
  ]
}
```

**响应示例：**
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "analysisId": "err_20260603_abc12345",
    "overallAssessment": "该学生在链表操作上存在系统性问题...",
    "errorPattern": "编译错误在首次提交后未得到解决，学生在第3次尝试后转为运行时错误...",
    "errorCategories": [
      {
        "type": "COMPILE_ERROR",
        "count": 2,
        "rootCause": "对ListNode结构体定义不熟悉，未正确引用头文件",
        "specificIssues": ["缺少结构体前向声明", "头文件引用顺序错误"],
        "suggestions": ["复习结构体定义语法", "学习C语言头文件引用规范"],
        "isSystemic": false
      }
    ],
    "learningSuggestions": [
      {
        "topic": "链表边界处理",
        "priority": "HIGH",
        "reason": "连续5次提交中出现3次空指针/边界问题",
        "suggestedResources": "复习教材第3章链表基本操作"
      }
    ],
    "interventionTriggered": true,
    "interventionMessage": "检测到你已连续提交5次，建议暂停提交，先查看错误分析报告再继续。加油！",
    "severity": "HIGH"
  }
}
```

### 2. POST `/ai/warning/analyze` — 学习预警分析

对班级学生的提交统计进行预警分析，识别需要教学干预的学生。

**请求示例：**
```json
{
  "classId": 10,
  "experimentId": 42,
  "experimentName": "实验三-链表",
  "deadline": "2026-06-10T23:59:00",
  "students": [
    {
      "studentId": "20220101001",
      "studentName": "张三",
      "totalSubmissions": 10,
      "acceptedCount": 1,
      "compileErrors": 3,
      "runtimeErrors": 2,
      "wrongAnswers": 4,
      "timeLimitExceeded": 0,
      "lastSubmissionAt": "2026-06-03T11:00:00"
    }
  ]
}
```

**响应示例：**
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "warnings": [
      {
        "studentId": "20220101001",
        "level": "HIGH",
        "triggered": true,
        "warningType": "FREQUENT_FAILURE",
        "warningMessage": "你已提交10次但通过率较低，建议暂停提交，先查看AI错误分析报告再继续。",
        "teacherNote": "提交10次，AC率仅10%，需要重点关注。",
        "suggestedActions": ["查看AI错误分析报告", "复习相关知识点", "向教师请教"],
        "autoNotify": true
      }
    ],
    "classSummary": "班级共60人，21人触发预警（35%）。建议教师在课堂上针对高频错误进行集中讲解。"
  }
}
```

### 3. POST `/ai/experiment/analyze` — 实验完成情况分析

从教学视角分析全班实验数据，给出教学改进建议。

**请求示例：**
```json
{
  "experimentId": 42,
  "experimentName": "实验三-链表",
  "classId": 10,
  "totalStudents": 60,
  "completed": 45,
  "inProgress": 10,
  "notStarted": 5,
  "avgSubmissions": 6.3,
  "avgPassRate": 0.72,
  "commonErrors": [
    {"type": "COMPILE_ERROR", "count": 45, "percentage": 35.0},
    {"type": "RUNTIME_ERROR", "count": 32, "percentage": 25.0}
  ],
  "problemStats": [
    {"label": "1-1 链表反转", "avgSubmissions": 8.2, "passRate": 0.34},
    {"label": "1-2 栈实现", "avgSubmissions": 3.1, "passRate": 0.85}
  ]
}
```

**响应示例：**
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "completionAssessment": "实验整体完成情况良好，45/60人已完成（75%）。...",
    "difficultyAnalysis": {
      "hardestProblem": "1-1 链表反转",
      "reason": "该题平均提交8.2次，AC率仅34%，是全班最大的拦路虎",
      "avgSubmissions": 8.2,
      "passRate": 0.34
    },
    "commonErrorAnalysis": "编译错误（35%）和运行时错误（25%）是最常见的问题类型...",
    "teachingSuggestions": [
      "建议在课堂上重点讲解链表反转的两种实现（迭代/递归）",
      "对于尚未开始的5名学生，建议逐个了解原因"
    ],
    "riskStudents": ["20220101001", "20220101015"]
  }
}
```

## 容错机制

当 DeepSeek API 不可用时（网络错误、API Key 无效等），服务会自动降级到**规则引擎**：
- 返回 200 状态码 + 完整的响应结构
- `overallAssessment` 中会标注「AI分析暂时不可用」
- 错误分类和学习建议基于预定义的规则模板生成
- 预警分析基于统计阈值判断，不依赖 AI

**Java 后端无需做任何特殊处理——接口始终返回有效的 JSON。**

## 开发

```bash
# 运行测试
uv run pytest

# 代码检查
uv run ruff check .

# 自动修复
uv run ruff check --fix .
```

## 给队友的集成指南

### 1号成员（后端核心）- Java 集成

1. 在 `application.properties` 添加：
```properties
error.analysis.service.url=http://127.0.0.1:8002
```

2. 创建 `ErrorAnalysisController`，调用本服务的三个接口
3. 创建数据库表存储分析结果（`ai_error_analysis`、`ai_warning`）
4. PTA 同步完成后自动触发分析（error count > 5 → 自动调用）

### 6号成员（前端）

1. 新增 `AIErrorAnalysis.vue` 页面展示错误分析报告
2. 在导航栏添加预警红点（调用 Java 后端的预警查询接口）
3. 教师端增加「实验分析」Tab，展示全班分析结果

### 调用流程建议

```
学生查看分析报告：
  frontend → Java: GET /api/ai/error/analysis/{studentId}
  Java: 从数据库读取缓存结果，或调用 error-analysis-service
  error-analysis-service → DeepSeek → 返回分析结果

PTA同步后自动分析：
  spider-repo 同步完成 → Java 检测 → 遍历学生
    → 若 errorCount > 5: 调用 POST /ai/error/analyze
    → 存储结果到 ai_error_analysis 表
  Java → 调用 POST /ai/warning/analyze（班级维度）
    → 存储预警到 ai_warning 表
```
