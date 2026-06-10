# Error Analysis Service

AI 驱动的代码错误分析微服务，为 PTA 教学辅助系统提供错误诊断、主动干预和学习建议能力。

**端口**: `8002` | **技术栈**: FastAPI + DeepSeek + OpenAI SDK | **负责人**: 3号成员 r2220

---

## 目录

1. [快速启动](#快速启动)
2. [架构总览](#架构总览)
3. [API 接口文档](#api-接口文档)
4. [后端集成详解](#后端集成详解)
5. [前端集成详解](#前端集成详解)
6. [Postman 测试指南](#postman-测试指南)

---

## 快速启动

```bash
cd D:/IDEA/Ptaapps/error-analysis-service

# 1. 创建虚拟环境 & 安装依赖
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY（没有 key 也能启动，走规则引擎降级）

# 3. 启动
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

- 健康检查：`GET http://127.0.0.1:8002/health`
- Swagger 文档：`http://127.0.0.1:8002/docs`

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│  前端 Vue :8080                                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ api/index.js                                                 │    │
│  │   analyzeError()          → POST /api/analysis/error         │    │
│  │   getWarningAnalysis()    → POST /api/analysis/warning       │    │
│  │   getLearningSuggestions()→ POST /api/analysis/learning      │    │
│  └───────────────────────────┬──────────────────────────────────┘    │
│                               │                                       │
│  ┌───────────────────────────┼──────────────────────────────────┐    │
│  │ 页面                     │                                    │    │
│  │  Dashboard.vue           ← getWarningAnalysis() → WarningBanner  │
│  │  LearningAnalysis.vue    ← analyzeError()       → ErrorAnalysisCard
│  │  Practice.vue            ← getLearningSuggestions() → weakPoints │
│  └───────────────────────────┼──────────────────────────────────┘    │
└──────────────────────────────┼───────────────────────────────────────┘
                               │  POST /api/analysis/*
┌──────────────────────────────┼───────────────────────────────────────┐
│  后端 Spring Boot :8081      │                                       │
│                              ▼                                       │
│  ErrorAnalysisController    (/api/analysis/*)                       │
│        │                                                             │
│  ErrorAnalysisServiceImpl                                           │
│        │  ├─ TeacherExperimentQueryDao.findSubmissionProblemRows()   │
│        │  ├─ Native SQL: student_profile, student_problem_attempt   │
│        │  ├─ Native SQL: student_skill_state, ai_remarks            │
│        │  └─ Native SQL: assignment_offering, assignment_template   │
│        │                                                             │
│  RestTemplate → POST http://127.0.0.1:8002/analyze/*                │
└──────────────────────────────┼───────────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────────┐
│  error-analysis-service :8002│                                       │
│                              ▼                                       │
│  POST /analyze/error      → error_analyzer.py   → DeepSeek API      │
│  POST /analyze/warning    → warning_detector.py → DeepSeek API      │
│  POST /analyze/learning   → learning_advisor.py → DeepSeek API      │
│                                                                      │
│  降级: DeepSeek 不可用时自动走规则引擎，始终返回 200                   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## API 接口文档

所有接口返回统一格式：`{"code": 200, "message": "success", "data": {...}}`

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | — | DeepSeek API Key（为空时走规则引擎降级） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名称 |
| `SERVICE_HOST` | `0.0.0.0` | 监听地址 |
| `SERVICE_PORT` | `8002` | 服务端口 |

---

### 1. POST `/analyze/error` — AI 错误分析

```json
// Request
{
  "studentId": "20220101001",
  "studentName": "张三",
  "experimentId": 42,
  "experimentName": "实验三-链表",
  "problemTitle": "链表反转",
  "problemDescription": "给定一个单链表的头节点 head，请反转链表...",
  "submissions": [{
    "attemptNo": 1,
    "judgeStatus": "COMPILE_ERROR",
    "compiler": "GCC",
    "errorMessage": "error: 'ListNode' was not declared in this scope",
    "code": "#include <stdio.h>\n...",
    "submittedAt": "2026-06-05T10:30:00",
    "runtimeMs": null,
    "memoryKb": null
  }]
}

// Response data.analysisId          — 唯一 ID (err_YYYYMMDD_hex8)
// Response data.overallAssessment   — 综合诊断
// Response data.errorCategories[]   — 错误分类 (type, count, rootCause, specificIssues, suggestions, isSystemic)
// Response data.learningSuggestions[] — 学习建议 (topic, priority, reason, suggestedResources)
// Response data.interventionTriggered — 是否需要干预
// Response data.severity              — HIGH / MEDIUM / LOW
// Response data.aiGenerated           — true=AI / false=规则引擎降级
```

---

### 2. POST `/analyze/warning` — AI 主动干预

```
触发条件: 错误次数 > 5（服务内部判断）
串联逻辑: 如果后端传了 submissions/errorHistory/skillStates，内部自动调 /analyze/error + /analyze/learning
返回: WarningResult（未触发）或 WarningCombinedData（触发时含三层嵌套结果）
```

**基础请求（仅预警）：**
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

**附加 submissions 时（触发串联）：**
```json
{
  // 以上所有字段 +
  "submissions": [ /* 同 /analyze/error 的 submissions */ ],
  "errorHistory": [{"errorType": "COMPILE_ERROR", "count": 3}],
  "skillStates": [{"tagName": "指针", "masteryScore": 35.0, "attemptCount": 8}]
}
```

**串联返回（WarningCombinedData）：**
```json
{
  "triggered": true,
  "warning": { "level": "HIGH", "warningType": "FREQUENT_FAILURE", "warningMessage": "...", ... },
  "errorAnalysis": { "analysisId": "...", "errorCategories": [...], ... },
  "learningSuggestions": { "suggestionId": "...", "weakPoints": [...], ... }
}
```

---

### 3. POST `/analyze/learning` — AI 学习建议生成

```json
// Request
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
  "previousRemark": null
}

// Response data.weakPoints[]    — 薄弱知识点 (tagName, severity, reason)
// Response data.studyPlan[]     — 学习计划 (topic, priority, suggestedResources, estimatedTime)
// Response data.summaryMessage  — 总结鼓励语
// Response data.aiGenerated     — true/false
```

---

### 容错机制

DeepSeek 不可用时自动降级到规则引擎：返回 200 + `aiGenerated: false`，所有字段都有合理默认值。**后端无需特殊处理**。

---

## 后端集成详解

### 后端文件索引

```
backend-repo/src/main/java/com/tap/backend/academic/
├── controller/
│   ├── ErrorAnalysisController.java     ← 对前端暴露 /api/analysis/*
│   └── ApiController.java               ← submitExperiment() 异步触发
├── service/
│   ├── ErrorAnalysisService.java        ← 接口 (5个方法)
│   └── impl/
│       └── ErrorAnalysisServiceImpl.java ← 实现 (RestTemplate + 原生SQL)
├── dao/
│   └── teacherexperiment/
│       └── TeacherExperimentQueryDao.java ← MyBatis 注解 SQL
└── teacherexperiment/
    └── TeacherSubmissionProblemRow.java   ← DTO 行对象

backend-repo/src/main/resources/
├── application.yml                       ← 默认配置
├── application-dev.yml                   ← dev 覆盖 (密码 123456)
└── application-local.yml                 ← local 覆盖 (error-analysis base-url)
```

### 后端接口（Controller）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/analysis/health` | 健康检查 |
| `POST` | `/api/analysis/error` | 错误分析（需 `{experimentId}`） |
| `POST` | `/api/analysis/warning` | 预警分析（需 `{experimentId}`） |
| `POST` | `/api/analysis/learning` | 学习建议 |
| `POST` | `/api/analysis/intervention` | 主动干预全流程 |

所有接口通过 `StudentSessionResolver` 从 HTTP Session 取 `studentId`，**必须先 POST `/api/login` 拿 cookie**。

### 后端调用微服务方式

```java
// ErrorAnalysisServiceImpl.java 第 53 行
private final RestTemplate restTemplate = new RestTemplate();

// 第 50 行 — 微服务地址
@Value("${tap.error-analysis.base-url:http://127.0.0.1:8002}")
private String errorAnalysisBaseUrl;

// 第 128 行 — 实际调用
String url = errorAnalysisBaseUrl + "/analyze/error";
Map<String, Object> responseBody = restTemplate.postForEntity(url, entity, Map.class).getBody();
// 从 {code, message, data} 里取 data 部分返回
return (Map<String, Object>) responseBody.get("data");
```

### 数据库查询详解

#### 主查询：`findSubmissionProblemRows()` (DAO 219-242行)

```sql
SELECT
  CAST(ap.sort_order AS SIGNED) AS sortOrder,
  ap.problem_no    AS problemNo,
  ap.title         AS problemTitle,
  sps.latest_status   AS latestStatus,
  sps.best_score      AS bestScore,
  sps.attempt_count   AS attemptCount,
  spa.submitted_at    AS submitTime,
  code_artifact.text_content AS code
FROM student_profile sp
JOIN student_problem_state sps
  ON sps.student_id = sp.id
 AND sps.offering_id = #{experimentId}
JOIN assignment_problem ap ON ap.id = sps.problem_id
LEFT JOIN student_problem_attempt spa ON spa.id = sps.latest_attempt_id   -- ⚠️ 只有最后一次
LEFT JOIN artifact code_artifact ON code_artifact.id = sps.latest_code_artifact_id
WHERE sp.student_no = #{studentId}
ORDER BY ap.sort_order, ap.id
```

**涉及的表**: `student_profile`, `student_problem_state`, `assignment_problem`, `student_problem_attempt`, `artifact`

#### 补充查询（ErrorAnalysisServiceImpl 中的 Native SQL）

| 方法 | 行号 | 查的表 | 取的字段 |
|------|------|--------|---------|
| `resolveStudentName()` | 569-581 | `student_profile` | `real_name` |
| 查实验名称 | 83-88 | `assignment_offering` + `assignment_template` | `title` |
| 查截止日期 | 482-489 | `assignment_offering` | `deadline_at` |
| `countErrorsFromAttempts()` | 221-238 | `student_problem_attempt` + `student_profile` | `COUNT(*)` (非 ACCEPTED) |
| `querySubmissionStats()` | 408-506 | 用 `findSubmissionProblemRows` 结果 + Java 端统计 | 编译/运行/答案错误/超时次数 |
| `queryErrorDistribution()` | 511-535 | `student_problem_state` + `student_problem_attempt` + `student_profile` | `judge_status`, `COUNT(*)` |
| `querySkillStatesByStudentNo()` | 540-563 | `student_skill_state` + `student_profile` | `tag_name`, `mastery_score`, `attempt_count` |
| `getLatestExperimentId()` | 586-601 | `student_problem_state` + `student_profile` | `offering_id` |

### 异步触发流程

```
ApiController.submitExperiment()  (POST /experiments/{id}/submit)
  │  保存提交成功后
  └→ CompletableFuture.runAsync()
       │
       ├─ errorCount >= 6 → proactiveIntervention()
       │    ├─ analyzeErrors()      → POST :8002/analyze/error
       │    ├─ generateLearningSuggestions() → POST :8002/analyze/learning
       │    └─ checkWarning()       → POST :8002/analyze/warning
       │
       └─ errorCount > 0 → analyzeErrors()
            └─ POST :8002/analyze/error
```

### 当前数据缺口

| 字段 | 数据库里有？ | 哪张表 | 当前拿到没 |
|------|:----:|--------|:----:|
| `studentId` | ✅ | `student_profile.student_no` | ✅ |
| `studentName` | ✅ | `student_profile.real_name` | ✅ |
| `experimentName` | ✅ | `assignment_template.title` | ✅ |
| `problemTitle` | ✅ | `assignment_problem.title` | ✅ |
| `problemDescription` | ❌ | — | ❌ 写死为 null |
| `judgeStatus` | ✅ | `student_problem_state.latest_status` | ⚠️ 只有最后一次 |
| `compiler` | ✅ | `student_problem_attempt.compiler` | ❌ 写死为 "GCC" |
| `errorMessage` | ✅ | `pta_raw_submission_row.raw_json` | ❌ 写死为 null |
| `code` | ✅ | `artifact.text_content` | ⚠️ 只有最后一次 |
| `submittedAt` | ✅ | `student_problem_attempt.submitted_at` | ⚠️ 只有最后一次 |
| `runtimeMs` | ✅ | `student_problem_attempt.runtime_ms` | ❌ 没传 |
| `memoryKb` | ✅ | `student_problem_attempt.memory_kb` | ❌ 没传 |

> **关键外键链**: `student_problem_attempt.raw_row_id` → `pta_raw_submission_row.id` → `raw_json` (含完整报错信息)，当前没走这条链。

---

## 前端集成详解

### 前端文件索引

```
fronted-repo/src/
├── api/
│   └── index.js                                    ← API 函数定义 (334-343行)
│
├── views/student/
│   ├── Dashboard.vue                                ← 调用 getWarningAnalysis() (222行)
│   │   └── <WarningBanner />                        ← 预警横幅 (8行)
│   ├── LearningAnalysis.vue                         ← 调用 analyzeError() (389行)
│   │   └── <ErrorAnalysisCard />                    ← 错误分析卡片 (174行)
│   ├── Practice.vue                                 ← 调用 getLearningSuggestions() (659行)
│   │   └── 展示 weakPoints 标签
│   └── components/
│       ├── WarningBanner.vue                        ← 预警横幅组件
│       └── ErrorAnalysisCard.vue                    ← 错误分析卡片组件
│
└── router/
    └── index.js                                     ← 路由定义 (/student/*)
```

### 前端 API 函数

```javascript
// fronted-repo/src/api/index.js 第 334-343 行

async analyzeError(payload) {
  return apiClient.post('/api/analysis/error', payload, { timeout: 60000 })
}

async getWarningAnalysis(payload) {
  return apiClient.post('/api/analysis/warning', payload, { timeout: 60000 })
}

async getLearningSuggestions(payload) {
  return apiClient.post('/api/analysis/learning', payload, { timeout: 60000 })
}
```

### 前端调用位置

| 页面 URL | 页面文件 | 调用的 API | 传了什么 | 渲染组件 |
|---------|---------|-----------|---------|---------|
| `/student/dashboard` | `Dashboard.vue:222` | `getWarningAnalysis()` | `{studentId}` | `WarningBanner` |
| `/student/learning-analysis` | `LearningAnalysis.vue:389` | `analyzeError()` | `{studentId}` | `ErrorAnalysisCard` |
| `/student/practice` | `Practice.vue:659` | `getLearningSuggestions()` | `{studentId}` | weakPoints 标签 |

### Vue DevServer 代理（vue.config.js）

```javascript
// /api/*   → http://localhost:8081   (所有 API 走后端)
// /error-analysis/* → http://127.0.0.1:8002  (直连微服务，备用)
```

> ⚠️ **当前问题**: 前端只传 `{studentId}` 没传 `experimentId`，error 和 warning 接口会 400。Learning 接口不强制需要 experimentId。

---

## Postman 测试指南

### 第 1 步：登录获取 Session

```
POST http://localhost:8081/api/login
Content-Type: application/json

{
    "username": "你的账号",
    "password": "你的密码",
    "role": "student"
}
```

返回 `{"success": true, ...}`，同时 Response Headers 里有 `Set-Cookie: JSESSIONID=xxx`。Postman 自动保存，后续请求不需要手动带。

### 第 2 步：查数据库获取测试参数

```sql
-- 找实验 ID
SELECT ao.id, at.title
FROM assignment_offering ao
JOIN assignment_template at ON at.id = ao.template_id
LIMIT 5;

-- 找学生学号
SELECT student_no, real_name FROM student_profile LIMIT 5;
```

### 第 3 步：测试三个接口

**错误分析：**
```
POST http://localhost:8081/api/analysis/error
Content-Type: application/json

{
    "studentId": "查到的学号",
    "experimentId": 查到的实验ID
}
```

**预警分析：**
```
POST http://localhost:8081/api/analysis/warning
Content-Type: application/json

{
    "studentId": "查到的学号",
    "experimentId": 查到的实验ID
}
```

**学习建议：**
```
POST http://localhost:8081/api/analysis/learning
Content-Type: application/json

{}
```
（studentId 从 session 自动取）

### 第 4 步：直连微服务测试（跳过认证）

如果不走后端代理，直接调微服务（不需要登录）：

```
POST http://localhost:8002/analyze/error
Content-Type: application/json

{
    "studentId": "2024001",
    "studentName": "测试",
    "experimentId": 1,
    "experimentName": "测试实验",
    "problemTitle": "链表反转",
    "submissions": [{
        "attemptNo": 1,
        "judgeStatus": "COMPILE_ERROR",
        "compiler": "gcc",
        "errorMessage": "error: missing ';'",
        "code": "int main() { return 0 }",
        "submittedAt": "2026-06-10T09:00:00"
    }]
}
```

---

## 项目路径总览

```
D:/IDEA/Ptaapps/
├── error-analysis-service/          ← 你的微服务 (3号负责)
│   ├── app/
│   │   ├── main.py                  ← FastAPI 入口
│   │   ├── api/
│   │   │   ├── error_analyze.py     ← POST /analyze/error
│   │   │   ├── warning_analyze.py   ← POST /analyze/warning
│   │   │   └── learning_suggest.py  ← POST /analyze/learning
│   │   ├── schemas/
│   │   │   └── requests.py          ← 所有 Pydantic 模型
│   │   ├── services/
│   │   │   ├── error_analyzer.py    ← 错误分析逻辑
│   │   │   ├── warning_detector.py  ← 预警检测 + 内部串联
│   │   │   ├── learning_advisor.py  ← 学习建议生成
│   │   │   └── deepseek_client.py   ← DeepSeek HTTP 客户端
│   │   └── core/
│   │       ├── config.py            ← Settings (env)
│   │       └── responses.py         ← ApiResponse[T] 统一响应
│   ├── .env                         ← API Key 配置
│   └── .env.example
│
├── backend-repo/                    ← Java 后端 (1号负责)
│   └── src/main/
│       ├── java/com/tap/backend/academic/
│       │   ├── controller/ErrorAnalysisController.java
│       │   ├── service/ErrorAnalysisService.java
│       │   ├── service/impl/ErrorAnalysisServiceImpl.java
│       │   └── dao/teacherexperiment/TeacherExperimentQueryDao.java
│       └── resources/
│           ├── db/migration/        ← 数据库迁移脚本
│           ├── application.yml
│           └── application-dev.yml
│
└── fronted-repo/                    ← Vue 前端 (6号负责)
    └── src/
        ├── api/index.js             ← API 函数
        ├── views/student/
        │   ├── Dashboard.vue
        │   ├── LearningAnalysis.vue
        │   ├── Practice.vue
        │   └── components/
        │       ├── WarningBanner.vue
        │       └── ErrorAnalysisCard.vue
        └── router/index.js
```
