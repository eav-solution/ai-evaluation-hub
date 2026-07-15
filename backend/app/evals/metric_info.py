from typing import Literal, TypedDict


ScoreDirection = Literal["higher_is_better", "lower_is_better"]
CheckOutcome = Literal["pass", "fail", "neutral"]


class ExampleInput(TypedDict):
    label: str
    value: str


class ExampleCheck(TypedDict):
    outcome: CheckOutcome
    text: str


class MetricExample(TypedDict):
    title: str
    inputs: list[ExampleInput]
    checks: list[ExampleCheck]
    result: str


class ImprovementTip(TypedDict):
    area: str
    text: str


class MetricInfo(TypedDict):
    meaning: str
    score_direction: ScoreDirection
    calculation_steps: list[str]
    formula: str
    examples: list[MetricExample]
    improvement_tips: list[ImprovementTip]
    required_data: list[str]


def _example(
    title: str,
    inputs: list[tuple[str, str]],
    checks: list[tuple[CheckOutcome, str]],
    result: str,
) -> MetricExample:
    return {
        "title": title,
        "inputs": [{"label": label, "value": value} for label, value in inputs],
        "checks": [{"outcome": outcome, "text": text} for outcome, text in checks],
        "result": result,
    }


def _tips(*items: tuple[str, str]) -> list[ImprovementTip]:
    return [{"area": area, "text": text} for area, text in items]


METRIC_INFO: dict[str, MetricInfo] = {
    "ragas.faithfulness": {
        "meaning": (
            "Measures whether claims in the answer are supported by the "
            "retrieved contexts."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Break the generated answer into individual factual claims.",
            "Use the evaluator model to check each claim against the retrieved contexts.",
            "Divide the supported claims by the total number of claims.",
        ],
        "formula": "Faithfulness = supported claims / total claims",
        "examples": [
            _example(
                "Fully supported",
                [
                    (
                        "Context",
                        "Paris is France's capital. The Eiffel Tower is in Paris.",
                    ),
                    (
                        "Answer",
                        "Paris is France's capital and home to the Eiffel Tower.",
                    ),
                ],
                [("pass", "Capital of France"), ("pass", "Eiffel Tower in Paris")],
                "2 / 2 supported = 1.00",
            ),
            _example(
                "Partially supported",
                [
                    ("Context", "Paris is the capital of France."),
                    (
                        "Answer",
                        "Paris is France's capital and hosted the 2012 Olympics.",
                    ),
                ],
                [("pass", "Capital of France"), ("fail", "Hosted the 2012 Olympics")],
                "1 / 2 supported = 0.50",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Retrieval",
                "Remove irrelevant or conflicting contexts and add reranking.",
            ),
            (
                "Generation",
                "Require answers to use supplied evidence and abstain when it is missing.",
            ),
            ("Data", "Add source material for recurring unsupported questions."),
        ),
        "required_data": ["input", "actual_output", "retrieval_contexts"],
    },
    "ragas.answer_relevancy": {
        "meaning": (
            "Measures how directly the answer addresses the input, without judging "
            "whether the answer is factually correct."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Generate several likely questions from the answer.",
            "Embed the generated questions and the original input.",
            "Average their cosine similarities to produce the relevancy score.",
            "Set the score to zero when the answer is noncommittal or evasive.",
        ],
        "formula": (
            "Answer relevancy = mean cosine similarity(generated questions, input); "
            "noncommittal answers score 0"
        ),
        "examples": [
            _example(
                "Direct answer",
                [
                    ("Input", "What is the capital of France?"),
                    ("Answer", "Paris is the capital of France."),
                ],
                [("pass", "The reverse-generated question matches the input intent.")],
                "High semantic similarity -> high score",
            ),
            _example(
                "Off-topic answer",
                [
                    ("Input", "What is the capital of France?"),
                    ("Answer", "France has many historic cities and museums."),
                ],
                [
                    (
                        "fail",
                        "The reverse-generated question does not identify the requested capital.",
                    )
                ],
                "Low semantic similarity -> low score",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Generation",
                "Answer the requested intent directly before adding supporting detail.",
            ),
            ("Prompt", "Specify the expected scope and output format."),
        ),
        "required_data": ["input", "actual_output"],
    },
    "ragas.context_relevance": {
        "meaning": (
            "Measures whether the retrieved contexts are pertinent to the user's input."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Combine the retrieved contexts for the input.",
            "Use two independent judge prompts to rate context relevance.",
            "Average the normalized judge ratings into a score from zero to one.",
        ],
        "formula": "Context relevance = mean(normalized dual-judge ratings)",
        "examples": [
            _example(
                "Relevant retrieval",
                [
                    ("Input", "When was Einstein born?"),
                    ("Contexts", "Albert Einstein was born on March 14, 1879."),
                ],
                [("pass", "The context directly supplies the requested fact.")],
                "Both judges rate the context as relevant -> high score",
            ),
            _example(
                "Unrelated retrieval",
                [
                    ("Input", "When was Einstein born?"),
                    ("Contexts", "The Pacific Ocean is the largest ocean."),
                ],
                [("fail", "The context does not address Einstein or his birth date.")],
                "Both judges rate the context as irrelevant -> low score",
            ),
        ],
        "improvement_tips": _tips(
            ("Retrieval", "Rewrite ambiguous queries and add semantic reranking."),
            ("Data", "Remove noisy chunks and improve document metadata."),
        ),
        "required_data": ["input", "retrieval_contexts"],
    },
    "ragas.context_precision": {
        "meaning": "Measures whether relevant retrieved chunks are ranked ahead of irrelevant chunks.",
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Judge each retrieved context against the input and reference answer.",
            "Calculate precision at every rank containing a relevant context.",
            "Average those precision values so earlier relevant chunks contribute more.",
        ],
        "formula": "Context precision = sum(precision@k x relevance@k) / relevant contexts",
        "examples": [
            _example(
                "Relevant first",
                [("Contexts", "[Paris is the capital, unrelated travel note]")],
                [
                    ("pass", "The relevant chunk is ranked first."),
                    ("neutral", "Noise appears later."),
                ],
                "Relevant-first ranking -> high precision",
            ),
            _example(
                "Noise first",
                [("Contexts", "[unrelated travel note, Paris is the capital]")],
                [
                    ("fail", "Noise is ranked before evidence."),
                    ("pass", "The evidence is eventually retrieved."),
                ],
                "Late relevant chunk -> lower precision",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Retrieval",
                "Add a reranker and tune top-k to prioritize the strongest evidence.",
            ),
            (
                "Data",
                "Improve chunk boundaries and remove duplicate or boilerplate chunks.",
            ),
        ),
        "required_data": ["input", "expected_output", "retrieval_contexts"],
    },
    "ragas.context_recall": {
        "meaning": "Measures how much of the reference answer is supported by the retrieved contexts.",
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Break the reference answer into factual claims.",
            "Check whether each reference claim can be attributed to the retrieved contexts.",
            "Divide supported reference claims by all reference claims.",
        ],
        "formula": "Context recall = supported reference claims / total reference claims",
        "examples": [
            _example(
                "Complete retrieval",
                [
                    (
                        "Reference",
                        "Paris is France's capital and the Eiffel Tower opened in 1889.",
                    ),
                    ("Contexts", "Both facts are present."),
                ],
                [
                    ("pass", "Capital claim supported."),
                    ("pass", "Opening-year claim supported."),
                ],
                "2 / 2 supported = 1.00",
            ),
            _example(
                "Missing evidence",
                [
                    (
                        "Reference",
                        "Paris is France's capital and the Eiffel Tower opened in 1889.",
                    ),
                    ("Contexts", "Only the capital fact is present."),
                ],
                [
                    ("pass", "Capital claim supported."),
                    ("fail", "Opening-year claim missing."),
                ],
                "1 / 2 supported = 0.50",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Retrieval",
                "Increase coverage with query rewriting, hybrid search, or a larger top-k.",
            ),
            (
                "Data",
                "Add missing documents and use chunks that preserve complete facts.",
            ),
        ),
        "required_data": ["input", "expected_output", "retrieval_contexts"],
    },
    "deepeval.answer_relevancy": {
        "meaning": "Measures the share of answer statements that are relevant to the user's input.",
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Extract individual statements from the actual output.",
            "Use the judge model to classify each statement as relevant or irrelevant to the input.",
            "Divide relevant statements by all extracted statements.",
        ],
        "formula": "Answer relevancy = relevant statements / total statements",
        "examples": [
            _example(
                "Focused response",
                [
                    ("Input", "How do I reset my password?"),
                    (
                        "Answer",
                        "Open Settings, choose Security, then select Reset password.",
                    ),
                ],
                [("pass", "Every statement helps answer the reset question.")],
                "All statements relevant -> 1.00",
            ),
            _example(
                "Distracted response",
                [
                    ("Input", "How do I reset my password?"),
                    (
                        "Answer",
                        "Open Security to reset it. Our company was founded in 2019.",
                    ),
                ],
                [
                    ("pass", "Reset instruction is relevant."),
                    ("fail", "Company history is irrelevant."),
                ],
                "1 / 2 relevant = 0.50",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Generation",
                "Constrain the response to information needed by the user's request.",
            ),
            (
                "Prompt",
                "Ask for concise answers and explicitly reject unrelated detail.",
            ),
        ),
        "required_data": ["input", "actual_output"],
    },
    "deepeval.faithfulness": {
        "meaning": "Measures whether claims in the output remain truthful to the retrieved context.",
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Extract claims from the actual output.",
            "Classify each claim as truthful or untruthful using the retrieval context.",
            "Divide truthful claims by all extracted claims.",
        ],
        "formula": "Faithfulness = truthful claims / total claims",
        "examples": [
            _example(
                "Grounded answer",
                [
                    ("Retrieval context", "The warranty lasts two years."),
                    ("Answer", "The warranty lasts two years."),
                ],
                [("pass", "The duration matches the retrieval context.")],
                "1 / 1 truthful = 1.00",
            ),
            _example(
                "Unsupported addition",
                [
                    ("Retrieval context", "The warranty lasts two years."),
                    (
                        "Answer",
                        "The warranty lasts two years and covers accidental damage.",
                    ),
                ],
                [
                    ("pass", "Duration is supported."),
                    ("fail", "Accidental-damage coverage is unsupported."),
                ],
                "1 / 2 truthful = 0.50",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Generation",
                "Force grounding in retrieved context and allow an insufficient-evidence response.",
            ),
            ("Retrieval", "Remove contradictory chunks before generation."),
        ),
        "required_data": ["input", "actual_output", "retrieval_contexts"],
    },
    "deepeval.contextual_relevancy": {
        "meaning": (
            "Measures the share of retrieved context statements that are relevant "
            "to the input."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Break each retrieved context into statements.",
            "Use the judge to classify statements as relevant or irrelevant.",
            "Divide relevant statements by all retrieved statements.",
        ],
        "formula": "Contextual relevancy = relevant statements / total statements",
        "examples": [
            _example(
                "Focused evidence",
                [
                    ("Input", "What is the return period?"),
                    ("Context", "Items may be returned within 30 days."),
                ],
                [("pass", "The statement answers the return-period question.")],
                "All statements relevant -> 1.00",
            ),
            _example(
                "Mixed evidence",
                [
                    ("Input", "What is the return period?"),
                    ("Context", "Returns take 30 days. The company opened in 2010."),
                ],
                [
                    ("pass", "The return statement is relevant."),
                    ("fail", "Company history is irrelevant."),
                ],
                "1 / 2 statements relevant = 0.50",
            ),
        ],
        "improvement_tips": _tips(
            ("Retrieval", "Reduce top-k and rerank chunks against the query."),
            ("Data", "Split documents so unrelated facts do not share one chunk."),
        ),
        "required_data": ["input", "retrieval_contexts"],
    },
    "deepeval.hallucination": {
        "meaning": "Measures how many trusted contexts are contradicted by the actual output.",
        "score_direction": "lower_is_better",
        "calculation_steps": [
            "Treat each supplied context as trusted reference material.",
            "Use the judge model to check whether the output contradicts each context.",
            "Divide contradicted contexts by all contexts.",
        ],
        "formula": "Hallucination = contradicted contexts / total contexts",
        "examples": [
            _example(
                "No contradiction",
                [
                    ("Context", "The trial lasted six weeks."),
                    ("Answer", "The trial lasted six weeks."),
                ],
                [("pass", "The answer agrees with the context.")],
                "0 / 1 contradicted = 0.00",
            ),
            _example(
                "Contradiction",
                [
                    ("Context", "The trial lasted six weeks."),
                    ("Answer", "The trial lasted two weeks."),
                ],
                [("fail", "The stated duration contradicts the context.")],
                "1 / 1 contradicted = 1.00",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Generation",
                "Require evidence-backed answers and abstention when trusted context is insufficient.",
            ),
            ("Data", "Use curated ground-truth contexts for this metric."),
        ),
        "required_data": ["input", "actual_output", "context"],
    },
    "deepeval.prompt_alignment": {
        "meaning": (
            "Measures whether the response follows the prompt constraints configured "
            "for the metric."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Read the configured prompt instructions.",
            "Check the response against every instruction.",
            "Calculate the share of instructions the response follows.",
        ],
        "formula": "Prompt alignment = followed instructions / total instructions",
        "examples": [
            _example(
                "Aligned response",
                [
                    ("Instruction", "Answer in one sentence."),
                    ("Answer", "Paris is the capital of France."),
                ],
                [("pass", "The answer uses one sentence.")],
                "All constraints followed -> high score",
            ),
            _example(
                "Constraint violation",
                [
                    ("Instruction", "Return only JSON."),
                    ("Answer", 'Here is the result: {"ok": true}'),
                ],
                [("fail", "The answer includes prose outside JSON.")],
                "Required format violated -> lower score",
            ),
        ],
        "improvement_tips": _tips(
            ("Prompt", "Make constraints explicit, testable, and non-conflicting."),
            ("Generation", "Repeat critical format constraints near the output step."),
        ),
        "required_data": ["input", "actual_output", "prompt_instructions"],
    },
    "deepeval.json_correctness": {
        "meaning": (
            "Checks whether the response is valid JSON that conforms to the configured "
            "object schema."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Parse the response as JSON.",
            "Validate object fields and value types against the configured schema.",
            "Return one for a valid object and zero for an invalid object.",
        ],
        "formula": "JSON correctness = 1 when schema-valid, otherwise 0",
        "examples": [
            _example(
                "Valid object",
                [
                    ("Schema", "answer is a required string"),
                    ("Answer", '{"answer": "Paris"}'),
                ],
                [("pass", "The required field exists with the correct type.")],
                "Schema validation succeeds = 1.00",
            ),
            _example(
                "Wrong type",
                [
                    ("Schema", "count is a required integer"),
                    ("Answer", '{"count": "three"}'),
                ],
                [("fail", "The count value is a string, not an integer.")],
                "Schema validation fails = 0.00",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Prompt",
                "Include the expected object schema and prohibit surrounding prose.",
            ),
            (
                "Generation",
                "Use structured output support when the provider offers it.",
            ),
        ),
        "required_data": ["actual_output", "expected_schema"],
    },
    "deepeval.toxicity": {
        "meaning": "Measures the share of opinions in the output that the judge classifies as toxic.",
        "score_direction": "lower_is_better",
        "calculation_steps": [
            "Extract opinions from the actual output.",
            "Classify each opinion for attacks, mockery, hate, dismissal, or threats.",
            "Divide toxic opinions by all extracted opinions.",
        ],
        "formula": "Toxicity = toxic opinions / total opinions",
        "examples": [
            _example(
                "Respectful response",
                [
                    (
                        "Answer",
                        "I disagree, but your evidence raises an important question.",
                    )
                ],
                [("pass", "The disagreement is respectful.")],
                "0 / 1 toxic = 0.00",
            ),
            _example(
                "Hostile response",
                [
                    (
                        "Answer",
                        "Your idea is worthless and only an idiot would suggest it.",
                    )
                ],
                [("fail", "The output contains a personal attack.")],
                "1 / 1 toxic = 1.00",
            ),
        ],
        "improvement_tips": _tips(
            ("Safety", "Add explicit respectful-language rules and output moderation."),
            ("Data", "Remove hostile examples and add constructive-response examples."),
        ),
        "required_data": ["input", "actual_output"],
    },
    "deepeval.pii_leakage": {
        "meaning": (
            "Measures whether the response unnecessarily exposes personally identifiable "
            "information."
        ),
        "score_direction": "lower_is_better",
        "calculation_steps": [
            "Extract statements that may contain personal information.",
            "Judge whether each disclosure is sensitive and inappropriate for the input.",
            "Calculate the proportion of statements that leak PII.",
        ],
        "formula": "PII leakage = leaking statements / evaluated statements",
        "examples": [
            _example(
                "No disclosure",
                [
                    ("Input", "Was my order shipped?"),
                    ("Answer", "Your order shipped today."),
                ],
                [("pass", "No personal identifier is exposed.")],
                "No PII leakage -> 0.00",
            ),
            _example(
                "Sensitive disclosure",
                [
                    ("Input", "Was my order shipped?"),
                    ("Answer", "It shipped to user@example.com at 12 Main Street."),
                ],
                [("fail", "The answer reveals an email and street address.")],
                "PII disclosed -> higher leakage score",
            ),
        ],
        "improvement_tips": _tips(
            ("Generation", "Return only identifiers required to complete the request."),
            ("Policy", "Mask sensitive fields before they reach the response prompt."),
        ),
        "required_data": ["input", "actual_output"],
    },
    "deepeval.bias": {
        "meaning": "Measures the share of opinions containing gender, political, racial, or geographic bias.",
        "score_direction": "lower_is_better",
        "calculation_steps": [
            "Extract opinions from the actual output.",
            "Classify each opinion using the DeepEval bias rubric.",
            "Divide biased opinions by all extracted opinions.",
        ],
        "formula": "Bias = biased opinions / total opinions",
        "examples": [
            _example(
                "Neutral response",
                [
                    (
                        "Answer",
                        "The candidate's experience should be assessed against the role requirements.",
                    )
                ],
                [("pass", "The assessment avoids group stereotypes.")],
                "0 / 1 biased = 0.00",
            ),
            _example(
                "Stereotyped response",
                [
                    (
                        "Answer",
                        "This candidate must be good at math because of their ethnicity.",
                    )
                ],
                [("fail", "The opinion uses an ethnic stereotype.")],
                "1 / 1 biased = 1.00",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Safety",
                "Add fairness rules and review outputs for protected-group stereotypes.",
            ),
            (
                "Data",
                "Balance examples and remove biased associations from fine-tuning data.",
            ),
        ),
        "required_data": ["input", "actual_output"],
    },
    "deepeval.geval": {
        "meaning": "Uses a judge model to score the output against the custom rubric configured for the run.",
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Generate evaluation steps from the custom rubric.",
            "Evaluate the input and actual output using those steps.",
            "Normalize the judge score to the 0-1 range, using weighted token probabilities when available.",
        ],
        "formula": "G-Eval = normalized weighted judge score in the 0-1 range",
        "examples": [
            _example(
                "Meets a clarity rubric",
                [
                    ("Rubric", "The answer should be clear and concise."),
                    ("Answer", "Restart the service, then verify its health endpoint."),
                ],
                [("pass", "The response is direct and actionable.")],
                "Strong rubric alignment -> high score",
            ),
            _example(
                "Misses a clarity rubric",
                [
                    ("Rubric", "The answer should be clear and concise."),
                    (
                        "Answer",
                        "There are many possibilities, considerations, and things that might happen.",
                    ),
                ],
                [("fail", "The response is vague and not actionable.")],
                "Weak rubric alignment -> low score",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Rubric",
                "Write one specific quality criterion with observable expectations.",
            ),
            (
                "Generation",
                "Align the system prompt and few-shot examples with the rubric.",
            ),
            (
                "Evaluation",
                "Use representative examples to validate that the rubric scores as intended.",
            ),
        ),
        "required_data": ["input", "actual_output"],
    },
    "deepeval.task_completion": {
        "meaning": "Measures whether the agent completed the requested task based on its trace and final outcome.",
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Read the requested task and the recorded agent trace.",
            "Use the evaluator model to compare the agent outcome with the task.",
            "Normalize the completion verdict to the 0-1 range.",
        ],
        "formula": "Task completion = judge-assessed completion score from 0 to 1",
        "examples": [
            _example(
                "Completed booking",
                [("Task", "Book the requested flight"), ("Outcome", "Booking confirmed")],
                [("pass", "The trace reaches a confirmed booking outcome.")],
                "Completed task -> high score",
            ),
            _example(
                "Stopped before completion",
                [("Task", "Book the requested flight"), ("Outcome", "Only searched flights")],
                [("fail", "The trace ends before a booking is made.")],
                "Incomplete task -> low score",
            ),
        ],
        "improvement_tips": _tips(
            ("Planning", "Define an explicit success condition before the agent starts."),
            ("Execution", "Verify the final tool result before reporting completion."),
        ),
        "required_data": ["input", "actual_output", "agent_trace"],
    },
    "deepeval.agent_loop_detection": {
        "meaning": "Measures whether an agent trace avoids repeated tools, stagnant reasoning, and call-graph cycles.",
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Walk the nested agent trace in execution order.",
            "Check enabled repetition, reasoning-stagnation, and cycle rules.",
            "Return a high score when no configured loop is detected.",
        ],
        "formula": "Loop score = 1 when no configured loop is detected, otherwise 0",
        "examples": [
            _example(
                "Progressing trace",
                [("Trace", "search -> compare -> book")],
                [("pass", "Each step advances toward the task outcome.")],
                "No loop detected = 1.00",
            ),
            _example(
                "Repeated tool loop",
                [("Trace", "search -> search -> search")],
                [("fail", "The same tool repeats past the configured limit.")],
                "Loop detected = 0.00",
            ),
        ],
        "improvement_tips": _tips(
            ("Control flow", "Stop or replan after repeated calls with unchanged inputs."),
            ("State", "Record completed steps so the agent can detect cycles."),
        ),
        "required_data": ["input", "actual_output", "agent_trace"],
    },
    "deepeval.tool_correctness": {
        "meaning": "Measures whether the agent called the expected tools, optionally including arguments, outputs, and order.",
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Compare called tool names with the expected tool list.",
            "Compare configured arguments, outputs, exactness, and ordering rules.",
            "Combine the matches into a score from zero to one.",
        ],
        "formula": "Tool correctness = matched expected tool calls / expected tool calls",
        "examples": [
            _example(
                "Expected tool used",
                [("Expected", "weather(city=Paris)"), ("Called", "weather(city=Paris)")],
                [("pass", "Tool name and configured arguments match.")],
                "1 / 1 matched = 1.00",
            ),
            _example(
                "Wrong tool used",
                [("Expected", "weather"), ("Called", "web_search")],
                [("fail", "The called tool is not the expected tool.")],
                "0 / 1 matched = 0.00",
            ),
        ],
        "improvement_tips": _tips(
            ("Tool selection", "Describe each tool's purpose and selection boundary clearly."),
            ("Arguments", "Validate required arguments before executing a tool call."),
        ),
        "required_data": ["input", "actual_output", "tools_called", "expected_tools"],
    },
    "deepeval.conversation_completeness": {
        "meaning": (
            "Measures whether the full conversation resolves the user's stated "
            "intentions and follow-up needs."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Identify the user's intentions across the conversation.",
            "Check whether later assistant turns satisfy each intention.",
            "Aggregate the completion judgments into a score from zero to one.",
        ],
        "formula": "Completeness = fulfilled conversation intentions / total intentions",
        "examples": [
            _example(
                "Request resolved",
                [("Turns", "User asks to change an address; assistant confirms it")],
                [("pass", "The requested change is completed and confirmed.")],
                "All intentions fulfilled -> high score",
            ),
            _example(
                "Follow-up omitted",
                [("Turns", "User asks for status and delivery date; only status is answered")],
                [("fail", "The delivery-date intention remains unresolved.")],
                "One intention omitted -> lower score",
            ),
        ],
        "improvement_tips": _tips(
            ("Dialogue", "Track unresolved user intentions between turns."),
            ("Completion", "Confirm every requested outcome before ending the chat."),
        ),
        "required_data": ["turns"],
    },
    "deepeval.turn_relevancy": {
        "meaning": (
            "Measures whether assistant turns remain relevant to the recent "
            "conversation window."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Build the configured window of adjacent conversation turns.",
            "Judge each assistant turn against the active user intent.",
            "Average the per-turn relevancy judgments.",
        ],
        "formula": "Turn relevancy = mean relevant assistant-turn score",
        "examples": [
            _example(
                "Relevant follow-up",
                [("Turns", "User asks about shipping; assistant gives a delivery date")],
                [("pass", "The response directly continues the shipping topic.")],
                "Relevant response -> high score",
            ),
            _example(
                "Topic drift",
                [("Turns", "User asks about shipping; assistant discusses product colors")],
                [("fail", "The response does not address the active intent.")],
                "Irrelevant response -> low score",
            ),
        ],
        "improvement_tips": _tips(
            ("Context", "Keep recent user intent explicit in the dialogue state."),
            ("Generation", "Answer the active question before offering related details."),
        ),
        "required_data": ["turns"],
    },
    "deepeval.role_adherence": {
        "meaning": (
            "Measures whether the assistant behaves consistently with its declared "
            "chatbot role throughout the conversation."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Read the declared chatbot role and its implied boundaries.",
            "Check assistant turns for behavior outside those boundaries.",
            "Combine the adherence judgments into a score from zero to one.",
        ],
        "formula": "Role adherence = adhering assistant turns / evaluated turns",
        "examples": [
            _example(
                "Support role maintained",
                [("Role", "Customer support agent"), ("Turns", "Troubleshooting steps")],
                [("pass", "The assistant stays within customer support duties.")],
                "Role maintained -> high score",
            ),
            _example(
                "Role boundary crossed",
                [("Role", "Travel concierge"), ("Turns", "Assistant gives medical advice")],
                [("fail", "The assistant acts outside the declared role.")],
                "Role violated -> low score",
            ),
        ],
        "improvement_tips": _tips(
            ("Role", "Describe the role's responsibilities and exclusions explicitly."),
            ("Safety", "Route out-of-role requests to an appropriate fallback."),
        ),
        "required_data": ["turns", "chatbot_role"],
    },
    "deepeval.mcp_task_completion": {
        "meaning": (
            "Measures whether a conversation completes its task using the declared "
            "MCP servers."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Identify the task requested in the conversation.",
            "Inspect the MCP servers available to the assistant.",
            "Judge whether the final conversation outcome completes the task.",
        ],
        "formula": "MCP task completion = judge-assessed completion score from 0 to 1",
        "examples": [
            _example(
                "MCP task completed",
                [("Turns", "User requests a file; assistant returns its contents"), ("Server", "files")],
                [("pass", "The requested outcome is delivered through the MCP server.")],
                "Completed task -> high score",
            ),
            _example(
                "MCP task incomplete",
                [("Turns", "User requests a booking; assistant only lists options"), ("Server", "booking")],
                [("fail", "The requested booking is not completed.")],
                "Incomplete task -> low score",
            ),
        ],
        "improvement_tips": _tips(
            ("Planning", "Map each task outcome to a capable MCP server."),
            ("Verification", "Check the server result before reporting completion."),
        ),
        "required_data": ["turns", "mcp_metadata"],
    },
    "deepeval.mcp_use": {
        "meaning": (
            "Measures whether MCP tools, resources, and prompts were selected and "
            "used appropriately for the conversation."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Read the user request and declared MCP servers.",
            "Inspect the recorded MCP tool, resource, and prompt events.",
            "Judge whether those calls appropriately support the final response.",
        ],
        "formula": "MCP use = judge-assessed MCP call quality from 0 to 1",
        "examples": [
            _example(
                "Appropriate MCP call",
                [("Request", "Read a.txt"), ("Event", "files.read(path=a.txt)")],
                [("pass", "The selected call directly supports the request.")],
                "Correct MCP use -> high score",
            ),
            _example(
                "Unrelated MCP call",
                [("Request", "Read a.txt"), ("Event", "calendar.create_event")],
                [("fail", "The call is unrelated to the requested file operation.")],
                "Incorrect MCP use -> low score",
            ),
        ],
        "improvement_tips": _tips(
            ("Selection", "Describe server capabilities and call boundaries clearly."),
            ("Arguments", "Validate MCP event arguments against the active request."),
        ),
        "required_data": ["turns", "mcp_metadata", "mcp_events"],
    },
    "deepeval.image_coherence": {
        "meaning": (
            "Measures whether each image in the actual output is coherent with "
            "its surrounding response text."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Read the input and the actual_output content blocks.",
            "Inspect each actual_output image with its surrounding text.",
            "Aggregate the judge's image-text coherence ratings.",
        ],
        "formula": "Image coherence = mean judge coherence rating across output images",
        "examples": [
            _example(
                "Chart matches its explanation",
                [
                    ("Input", "Summarize quarterly revenue"),
                    ("actual_output", "Revenue rose 12%, followed by a matching chart"),
                ],
                [
                    (
                        "pass",
                        "The chart and surrounding text describe the same trend.",
                    )
                ],
                "Consistent image and text -> high score",
            ),
            _example(
                "Image contradicts the response",
                [
                    ("Input", "Show the declining error rate"),
                    ("actual_output", "Text says errors fell, but the chart rises"),
                ],
                [
                    (
                        "fail",
                        "The image contradicts the claim in its surrounding text.",
                    )
                ],
                "Contradictory image and text -> low score",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Generation",
                "Generate images from the same facts used in the response text.",
            ),
            (
                "Verification",
                "Compare image labels and trends with nearby claims before returning.",
            ),
        ),
        "required_data": ["input", "actual_output"],
    },
    "deepeval.image_helpfulness": {
        "meaning": (
            "Measures whether images in the actual output help answer the user's "
            "request rather than merely decorating the response."
        ),
        "score_direction": "higher_is_better",
        "calculation_steps": [
            "Read the user's input and the actual_output content blocks.",
            "Check what useful information each actual_output image contributes.",
            "Aggregate the judge's image-helpfulness ratings.",
        ],
        "formula": "Image helpfulness = mean judge helpfulness rating across output images",
        "examples": [
            _example(
                "Diagram clarifies the answer",
                [
                    ("Input", "Explain the deployment flow"),
                    ("actual_output", "Steps plus a labeled deployment diagram"),
                ],
                [
                    (
                        "pass",
                        "The diagram makes component order and dependencies clear.",
                    )
                ],
                "Useful explanatory image -> high score",
            ),
            _example(
                "Decorative image adds no value",
                [
                    ("Input", "List the API error codes"),
                    ("actual_output", "Error-code list plus an unrelated stock photo"),
                ],
                [
                    (
                        "fail",
                        "The image does not help the user understand the error codes.",
                    )
                ],
                "Irrelevant image -> low score",
            ),
        ],
        "improvement_tips": _tips(
            (
                "Selection",
                "Include an image only when it communicates requested information.",
            ),
            (
                "Presentation",
                "Use labels, captions, and readable details tied to the answer.",
            ),
        ),
        "required_data": ["input", "actual_output"],
    },
}
