import {fireEvent, render, screen} from "@testing-library/react";
import {describe, expect, it, vi} from "vitest";

import {MetricConfigForm} from "@/components/MetricConfigForm";
import type {Metric} from "@/lib/types";

const metric = {
  key: "test.configured",
  display_name: "Configured metric",
  config_schema: {
    type: "object",
    properties: {
      threshold: {
        title: "Threshold",
        anyOf: [
          {type: "number", minimum: 0, maximum: 1},
          {type: "null"},
        ],
      },
      include_reason: {type: "boolean", title: "Include reason"},
      rubric: {type: "string", title: "Rubric"},
      evaluation_fields: {
        type: "array",
        title: "Evaluation fields",
        items: {type: "string", enum: ["input", "actual_output", "context"]},
      },
      prompt_instructions: {
        type: "array",
        title: "Prompt instructions",
        items: {type: "string"},
      },
      expected_schema: {type: "object", title: "Expected schema"},
    },
  },
  default_config: {},
} as unknown as Metric;

describe("MetricConfigForm", () => {
  it("renders supported adapter metadata controls", () => {
    render(
      <MetricConfigForm
        metric={metric}
        value={{
          threshold: 0.5,
          include_reason: true,
          rubric: "Check quality",
          evaluation_fields: ["input"],
          prompt_instructions: ["Be concise", "Use JSON"],
          expected_schema: {type: "object", properties: {}},
        }}
        onChange={vi.fn()}
        onValidityChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Threshold")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("Include reason")).toHaveAttribute("type", "checkbox");
    expect(screen.getByLabelText("Rubric")).toHaveValue("Check quality");
    expect(screen.getByLabelText("Evaluation fields")).toHaveAttribute("multiple");
    expect(screen.getByLabelText("Prompt instructions")).toHaveValue("Be concise\nUse JSON");
    expect(screen.getByLabelText("Expected schema Advanced JSON")).toHaveValue(
      JSON.stringify({type: "object", properties: {}}, null, 2),
    );
  });

  it("keeps invalid Advanced JSON client-side and reports validity", () => {
    const onChange = vi.fn();
    const onValidityChange = vi.fn();
    render(
      <MetricConfigForm
        metric={metric}
        value={{expected_schema: {type: "object"}}}
        onChange={onChange}
        onValidityChange={onValidityChange}
      />,
    );

    const advanced = screen.getByLabelText("Expected schema Advanced JSON");
    fireEvent.change(advanced, {target: {value: "{"}});
    expect(screen.getByText("Enter valid JSON.")).toBeInTheDocument();
    expect(onValidityChange).toHaveBeenLastCalledWith(false);
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(advanced, {target: {value: '{"type":"object"}'}});
    expect(screen.queryByText("Enter valid JSON.")).not.toBeInTheDocument();
    expect(onValidityChange).toHaveBeenLastCalledWith(true);
    expect(onChange).toHaveBeenLastCalledWith({expected_schema: {type: "object"}});
  });

  it("renders Agentic adapter configuration controls from schema metadata", () => {
    const agentMetric = {
      ...metric,
      key: "test.agentic",
      config_schema: {
        type: "object",
        properties: {
          task: {anyOf: [{type: "string"}, {type: "null"}], title: "Task"},
          evaluation_params: {
            type: "array",
            title: "Evaluation params",
            items: {type: "string", enum: ["input_parameters", "output"]},
          },
          should_exact_match: {type: "boolean", title: "Should exact match"},
          should_consider_ordering: {type: "boolean", title: "Should consider ordering"},
          repetition_threshold: {type: "integer", title: "Repetition threshold"},
          similarity_threshold: {type: "number", title: "Similarity threshold"},
          check_tool_repetition: {type: "boolean", title: "Check tool repetition"},
          check_reasoning_stagnation: {type: "boolean", title: "Check reasoning stagnation"},
          check_call_graph_cycles: {type: "boolean", title: "Check call graph cycles"},
        },
      },
    } as Metric;

    render(
      <MetricConfigForm
        metric={agentMetric}
        value={{
          task: "Book the flight",
          evaluation_params: ["input_parameters"],
          should_exact_match: false,
          should_consider_ordering: true,
          repetition_threshold: 3,
          similarity_threshold: 0.85,
          check_tool_repetition: true,
          check_reasoning_stagnation: true,
          check_call_graph_cycles: true,
        }}
        onChange={vi.fn()}
        onValidityChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Task")).toHaveValue("Book the flight");
    expect(screen.getByLabelText("Evaluation params")).toHaveAttribute("multiple");
    expect(screen.getByLabelText("Should exact match")).toHaveAttribute("type", "checkbox");
    expect(screen.getByLabelText("Should consider ordering")).toBeChecked();
    expect(screen.getByLabelText("Repetition threshold")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("Similarity threshold")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("Check tool repetition")).toBeChecked();
    expect(screen.getByLabelText("Check reasoning stagnation")).toBeChecked();
    expect(screen.getByLabelText("Check call graph cycles")).toBeChecked();
  });
});
