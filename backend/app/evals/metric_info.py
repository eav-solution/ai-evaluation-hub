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
}
