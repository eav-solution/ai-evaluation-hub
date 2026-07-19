# Sample Datasets — Bộ dữ liệu kiểm chứng metrics

Mỗi metric có **1 file riêng, đúng 3 records** theo thứ tự cố định:

| Record | `case` | Ý nghĩa | Điểm kỳ vọng* |
|---|---|---|---|
| 1 | `case_1_all_correct` | Toàn bộ đúng | Tốt nhất (~1.0, hoặc ~0.0 với metric "lower is better") |
| 2 | `case_2_all_wrong` | Toàn bộ sai | Tệ nhất (~0.0, hoặc ~1.0 với metric "lower is better") |
| 3 | `case_3_half` | Nửa đúng, nửa sai | Quanh giữa (~0.5) |

\* Metric dùng LLM judge cho điểm **xấp xỉ** — quan trọng là thứ tự record 1 > record 3 > record 2 (hoặc ngược lại với lower-is-better). Hai metric deterministic (Tool Correctness, Agent Loop Detection) cho điểm chính xác tuyệt đối, ghi rõ bên dưới.

Cột `case` và `note` chỉ để đọc — **không cần map** khi cấu hình dataset. Các cột còn lại đặt tên trùng khớp schema field của app, map 1:1 là chạy.

Nội dung toàn kiến thức phổ thông (màu sắc, số học, con vật) — đọc là kiểm chứng được ngay.

---

## RAG

### `rag/generation/`

| File | Metric | Map cột | Điểm kỳ vọng (R1 / R2 / R3) |
|---|---|---|---|
| `ragas_faithfulness.csv` | Faithfulness (RAGAS) | input, actual_output, retrieval_contexts | ~1.0 / ~0.0 / ~0.5 |
| `ragas_answer_relevancy.csv` | Answer Relevancy (RAGAS) — cần cấu hình **embedding** | input, actual_output | cao / ~0.0 / giữa |
| `deepeval_answer_relevancy.csv` | Answer Relevancy (DeepEval) | input, actual_output | ~1.0 / ~0.0 / ~0.5 |
| `deepeval_faithfulness.csv` | Faithfulness (DeepEval) | input, actual_output, retrieval_contexts | ~1.0 / ~0.0 / ~0.5 |

Cách kiểm: câu trả lời có 2 mệnh đề (vd. "sky is blue" + "grass is green"). R1 cả 2 khớp context, R2 cả 2 trái context, R3 khớp 1 trái 1.

### `rag/retrieval/`

| File | Metric | Map cột | Điểm kỳ vọng (R1 / R2 / R3) |
|---|---|---|---|
| `ragas_context_relevance.csv` | Context Relevancy | input, actual_output, retrieval_contexts | cao / ~0.0 / ~0.5 |
| `ragas_context_precision.csv` | Context Precision | input, actual_output, expected_output, retrieval_contexts | ~1.0 / ~0.0 / ~0.5 |
| `ragas_context_recall.csv` | Context Recall | input, actual_output, expected_output, retrieval_contexts | ~1.0 / ~0.0 / ~0.5 |
| `deepeval_contextual_relevancy.csv` | Contextual Relevancy | input, actual_output, retrieval_contexts | ~1.0 / ~0.0 / ~0.5 |

Lưu ý Context Precision R3: context đúng bị xếp **sau** context sai → precision@2 = 0.5 (metric này chấm thứ hạng).

---

## Agentic

Files JSON (nested trace). Sample kind: `agent_trace` — map input, actual_output, agent_trace (+ tools_called, expected_tools cho Tool Correctness).

### `agentic/trace/`

| File | Metric | Điểm kỳ vọng (R1 / R2 / R3) |
|---|---|---|
| `deepeval_task_completion.json` | Task Completion (LLM judge) | cao / thấp / giữa |
| `deepeval_agent_loop_detection.json` | Agent Loop Detection (**deterministic**) | **1.0 / 0.35 / 0.6** — chính xác tuyệt đối |

Loop Detection: R2 là vòng lặp settings→home→settings (0.35 là **sàn điểm** của metric, không xuống 0); R3 gọi lặp `check_order_status` 6 lần y hệt rồi mới hoàn thành việc.

### `agentic/tools/`

| File | Metric | Điểm kỳ vọng (R1 / R2 / R3) |
|---|---|---|
| `deepeval_tool_correctness.json` | Tool Correctness (**deterministic**, so tên tool) | **1.0 / 0.0 / 0.5** — chính xác tuyệt đối |

Expected tools: `get_weather` + `send_email`. R1 gọi đúng cả 2, R2 gọi 2 tool khác hẳn, R3 đúng 1 sai 1. Giữ config mặc định (không bật exact match / ordering).

### `agentic/mcp/`

Sample kind: `conversation` — map turns, mcp_metadata (+ mcp_events cho MCP Use).

| File | Metric | Điểm kỳ vọng (R1 / R2 / R3) |
|---|---|---|
| `deepeval_mcp_task_completion.json` | MCP Task Completion | cao / thấp / giữa |
| `deepeval_mcp_use.json` | MCP Use | cao / thấp / giữa |

Kịch bản: hỏi tính `2 + 3` qua calculator-server. R1 gọi tool `add` đúng args đúng kết quả; R2 gọi `get_weather` cho câu hỏi số học + bịa đáp án; R3 một call đúng + một call sai.

---

## General

### `general/text_safety/` (CSV, map input + actual_output trừ khi ghi khác)

| File | Metric | Hướng điểm | Điểm kỳ vọng (R1 / R2 / R3) | Config khi chạy |
|---|---|---|---|---|
| `deepeval_hallucination.csv` | Hallucination — map thêm **context** | **THẤP = TỐT** | ~0.0 / ~1.0 / ~0.5 | — |
| `deepeval_prompt_alignment.csv` | Prompt Alignment | cao = tốt | ~1.0 / ~0.0 / ~0.5 | Prompt instructions (2 dòng):<br>`Answer in English.`<br>`End the answer with the word DONE.` |
| `deepeval_json_correctness.csv` | JSON Correctness (binary 0/1) | cao = tốt | 1 / 0 / **0** | Expected schema:<br>`{"type":"object","properties":{"name":{"type":"string"},"age":{"type":"integer"}},"required":["name","age"]}` |
| `deepeval_toxicity.csv` | Toxicity | **THẤP = TỐT** | ~0.0 / ~1.0 / giữa | — |
| `deepeval_pii_leakage.csv` | PII Leakage | **THẤP = TỐT** | ~0.0 / cao / giữa | — |
| `deepeval_bias.csv` | Bias | **THẤP = TỐT** | ~0.0 / cao / giữa | — |
| `deepeval_geval.csv` | G-Eval | cao = tốt | cao / thấp / giữa | Rubric: `Check whether the answer gives the correct result for every arithmetic question in the input.` |

Lưu ý:
- Với 4 metric "THẤP = TỐT": record `case_1_all_correct` phải ra điểm **thấp nhất** — đó là kết quả đúng, đừng nhầm là metric sai.
- JSON Correctness R3 là JSON hợp lệ nhưng thiếu field bắt buộc → vẫn 0 (metric chỉ có 0/1, không có 0.5).
- Nội dung xúc phạm / thiên vị / lộ thông tin trong R2–R3 là **dữ liệu test cố ý**, thông tin cá nhân toàn giá trị giả định (số 555, example.com).

### `general/conversational/` (JSON, map turns; Role Adherence map thêm chatbot_role)

| File | Metric | Điểm kỳ vọng (R1 / R2 / R3) |
|---|---|---|
| `deepeval_conversation_completeness.json` | Conversation Completeness | ~1.0 / ~0.0 / ~0.5 |
| `deepeval_turn_relevancy.json` | Turn Relevancy | ~1.0 / ~0.0 / ~0.5 |
| `deepeval_role_adherence.json` | Role Adherence (role: math tutor) | ~1.0 / ~0.0 / ~0.5 |

Mẫu chung: 2 lượt assistant — R1 cả 2 đạt, R2 cả 2 hỏng, R3 đạt 1 hỏng 1.

### `general/multimodal/` (JSON, map input + actual_output; cần judge **multimodal**)

| File | Metric | Điểm kỳ vọng (R1 / R2 / R3) |
|---|---|---|
| `deepeval_image_coherence.json` | Image Coherence | cao / thấp / giữa |
| `deepeval_image_helpfulness.json` | Image Helpfulness | cao / thấp / giữa |

Ảnh là URL công khai (GitHub raw, đã kiểm tra hoạt động, mỗi ảnh < 200 KB) — mở URL trong trình duyệt để tự xác nhận nội dung:

- Mèo: `.../n02123045_tabby.JPEG` — mặt mèo tabby cận cảnh
- Chuối: `.../n07753592_banana.JPEG` — buồng chuối trên cây
- Táo xanh: `.../n07742313_Granny_Smith.JPEG` — quả táo Granny Smith
- Chó: `.../n02099601_golden_retriever.JPEG` — chó golden retriever trên cỏ

(gốc: `https://raw.githubusercontent.com/EliSchwartz/imagenet-sample-images/master/`)

Máy chạy backend phải truy cập được `raw.githubusercontent.com` (backend tự tải ảnh khi chấm). Kịch bản: R1 chữ và ảnh khớp (nói mèo → ảnh mèo); R2 lệch hoàn toàn (nói mèo → ảnh chuối); R3 hai ảnh, 1 khớp 1 lệch.

---

## Cách chạy nhanh

1. Upload file vào workspace (CSV/JSON đều được app nhận).
2. Mở dataset → map cột theo bảng trên (tên cột trùng tên field nên chọn thẳng).
3. Tạo run **static mode**, chọn đúng metric của file, set config nếu bảng có ghi.
4. So điểm 3 records với cột "Điểm kỳ vọng". Cột `note` trong từng record nhắc lại kỳ vọng của record đó.
