# Error Analysis Service

AI 驱动的代码错误分析微服务，为 PTA 教学辅助系统提供错误诊断、主动干预和学习建议能力。

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

---

### 1. POST `/analyze/error` — AI 错误分析

分析学生代码提交历史，诊断错误根因，生成学习建议。

**请求：**

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
      "code": "#include <stdio.h>\n...",
      "submittedAt": "2026-06-05T10:30:00"
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `studentId` | str | ✅ | 学号 |
| `studentName` | str | ✅ | 姓名 |
| `experimentId` | int | ✅ | 实验 ID |
| `experimentName` | str | ✅ | 实验名称 |
| `problemTitle` | str | ✅ | 题目标题 |
| `problemDescription` | str | — | 题目描述（可选上下文） |
| `submissions` | list | ✅ | 提交记录列表 |
| `submissions[].attemptNo` | int | ✅ | 第几次提交（从1开始） |
| `submissions[].judgeStatus` | str | ✅ | 判题状态：COMPILE_ERROR, RUNTIME_ERROR, WRONG_ANSWER, TIME_LIMIT_EXCEEDED, MEMORY_LIMIT_EXCEEDED, ACCEPTED |
| `submissions[].compiler` | str | — | 编译器（GCC, G++） |
| `submissions[].errorMessage` | str | — | 报错信息 |
| `submissions[].code` | str | ✅ | 源代码 |
| `submissions[].submittedAt` | str | — | 提交时间（ISO-8601） |

**响应：**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "analysisId": "err_20260605_abc12345",
    "overallAssessment": "该学生在链表操作上存在系统性问题...",
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
        "reason": "连续5次提交中出现3次空指针问题",
        "suggestedResources": "复习教材第3章链表基本操作"
      }
    ],
    "interventionTriggered": true,
    "interventionMessage": "检测到你已连续提交5次，建议暂停提交，先查看错误分析报告再继续。加油！",
    "severity": "HIGH",
    "aiGenerated": true
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `analysisId` | str | 分析唯一 ID |
| `overallAssessment` | str | 综合诊断（中文） |
| `errorCategories` | list | 错误分类 |
| `errorCategories[].type` | str | 错误类型 |
| `errorCategories[].count` | int | 出现次数 |
| `errorCategories[].rootCause` | str | 根本原因 |
| `errorCategories[].specificIssues` | list[str] | 具体问题 |
| `errorCategories[].suggestions` | list[str] | 改进建议 |
| `errorCategories[].isSystemic` | bool | 是否系统性薄弱点（≥3次） |
| `learningSuggestions` | list | 学习建议 |
| `learningSuggestions[].topic` | str | 知识点 |
| `learningSuggestions[].priority` | str | 优先级：HIGH / MEDIUM / LOW |
| `learningSuggestions[].reason` | str | 建议原因 |
| `learningSuggestions[].suggestedResources` | str | 推荐资源 |
| `interventionTriggered` | bool | 是否需要干预 |
| `interventionMessage` | str | 给学生看的提示语 |
| `severity` | str | HIGH / MEDIUM / LOW |
| `aiGenerated` | bool | true=AI生成，false=规则引擎降级 |

---

### 2. POST `/analyze/warning` — AI 主动干预

检测单个学生是否需要教学干预（触发条件：错误次数 > 5）。

**请求：**

```json
{
  "studentId": "20220101001",
  "studentName": "张三",
  "experimentId": 42,
  "experimentName": "实验三-链表",
  "deadline": "2026-06-10T23:59:00",
  "totalSubmissions": 10,
  "acceptedCount": 1,
  "totalProblems": 5,
  "compileErrors": 3,
  "runtimeErrors": 2,
  "wrongAnswers": 4,
  "timeLimitExceeded": 0,
  "lastSubmissionAt": "2026-06-05T11:00:00"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `studentId` | str | ✅ | 学号 |
| `studentName` | str | ✅ | 姓名 |
| `experimentId` | int | ✅ | 实验 ID |
| `experimentName` | str | ✅ | 实验名称 |
| `deadline` | str | — | 截止时间（ISO-8601） |
| `totalSubmissions` | int | ✅ | 总提交次数 |
| `acceptedCount` | int | ✅ | 已通过题数 |
| `totalProblems` | int | ✅ | 总题数 |
| `compileErrors` | int | ✅ | 编译错误次数 |
| `runtimeErrors` | int | ✅ | 运行时错误次数 |
| `wrongAnswers` | int | ✅ | 答案错误次数 |
| `timeLimitExceeded` | int | ✅ | 超时次数 |
| `lastSubmissionAt` | str | ✅ | 最近提交时间 |

**响应：**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "studentId": "20220101001",
    "level": "HIGH",
    "triggered": true,
    "warningType": "FREQUENT_FAILURE",
    "warningMessage": "你已提交10次但通过率较低，建议暂停提交，先查看AI错误分析报告再继续。",
    "teacherNote": "提交10次，通过率仅10%，需要重点关注。",
    "suggestedActions": ["查看AI错误分析报告", "复习相关知识点", "向教师请教"],
    "autoNotify": true,
    "aiGenerated": true
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `studentId` | str | 学号 |
| `level` | str | HIGH / MEDIUM / LOW / OK |
| `triggered` | bool | 是否触发告警 |
| `warningType` | str | FREQUENT_FAILURE / BASIC_SYNTAX / STUCK / DEADLINE_RISK / OK |
| `warningMessage` | str | 给学生看的提示 |
| `teacherNote` | str | 给老师看的备注 |
| `suggestedActions` | list[str] | 建议措施 |
| `autoNotify` | bool | 是否自动通知 |
| `aiGenerated` | bool | AI or 规则引擎 |

---

### 3. POST `/analyze/learning` — AI 学习建议生成

基于学生错误历史和技能状态，生成个性化学习建议。

**请求：**

```json
{
  "studentId": "20220101001",
  "studentName": "张三",
  "errorHistory": [
    {"errorType": "COMPILE_ERROR", "count": 5},
    {"errorType": "RUNTIME_ERROR", "count": 3}
  ],
  "skillStates": [
    {"tagName": "指针", "masteryScore": 35.0, "attemptCount": 8},
    {"tagName": "链表", "masteryScore": 60.0, "attemptCount": 5}
  ],
  "previousRemark": "上次分析指出该生在指针使用方面存在困难..."
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `studentId` | str | ✅ | 学号 |
| `studentName` | str | ✅ | 姓名 |
| `errorHistory` | list | ✅ | 错误类型分布 |
| `errorHistory[].errorType` | str | ✅ | 错误类型 |
| `errorHistory[].count` | int | ✅ | 出现次数 |
| `skillStates` | list | — | 技能掌握状态 |
| `skillStates[].tagName` | str | ✅ | 技能标签（如"指针"、"链表"） |
| `skillStates[].masteryScore` | float | ✅ | 掌握度 0-100 |
| `skillStates[].attemptCount` | int | — | 练习次数 |
| `previousRemark` | str | — | 上次AI评语 |

**响应：**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "suggestionId": "lrn_20260605_abc12345",
    "weakPoints": [
      {
        "tagName": "指针",
        "severity": "HIGH",
        "reason": "编译错误中5次涉及指针类型不匹配"
      }
    ],
    "studyPlan": [
      {
        "topic": "指针基础",
        "priority": "HIGH",
        "suggestedResources": "教材第3章 指针与内存管理",
        "estimatedTime": "1小时"
      }
    ],
    "recommendedProblems": ["PTA同类题目练习", "教材课后习题"],
    "summaryMessage": "根据你的提交记录分析...建议优先巩固指针基础，加油！",
    "aiGenerated": true
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `suggestionId` | str | 建议唯一 ID |
| `weakPoints` | list | 薄弱知识点 |
| `weakPoints[].tagName` | str | 知识点名称 |
| `weakPoints[].severity` | str | HIGH / MEDIUM / LOW |
| `weakPoints[].reason` | str | 识别原因 |
| `studyPlan` | list | 学习计划 |
| `studyPlan[].topic` | str | 学习主题 |
| `studyPlan[].priority` | str | HIGH / MEDIUM / LOW |
| `studyPlan[].suggestedResources` | str | 推荐资源 |
| `studyPlan[].estimatedTime` | str | 预估时间 |
| `recommendedProblems` | list[str] | 推荐练习方向 |
| `summaryMessage` | str | 总结鼓励语 |
| `aiGenerated` | bool | AI or 规则引擎 |

---

## 容错机制

当 DeepSeek API 不可用时（网络错误、API Key 无效等），服务会自动降级到**规则引擎**：
- 返回 200 状态码 + 完整的响应结构
- `aiGenerated` 字段为 `false`
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

## 集成指南

本服务为内部微服务，由 Java 后端调用，不直接暴露给前端。

### 调用流程

```
学生提交错误 → Java 后端检测
  ├─ 调用 POST /analyze/error（错误分析）
  ├─ 如果 error count > 5 → 调用 POST /analyze/warning（干预检测）
  └─ 错误分析完成后 → 调用 POST /analyze/learning（学习建议）
```

### Java 后端需准备的数据

三个接口的 request 数据均可从以下表获取：

| 数据 | 来源表 |
|------|--------|
| 提交记录（状态、编译器等） | `student_problem_attempt` |
| 报错信息 | `pta_raw_submission_row` |
| 源代码 | `artifact.text_content`（通过 `student_problem_state.latest_code_artifact_id`） |
| 学生技能状态 | `student_skill_state` |
| 历史评语 | `ai_remarks` |

### 存储方案

Java 后端可根据返回的 JSON 自行建表存储分析结果，本服务不持久化任何数据。
