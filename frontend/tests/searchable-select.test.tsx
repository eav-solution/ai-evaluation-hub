import {fireEvent, render, screen} from "@testing-library/react";
import {describe, expect, it, vi} from "vitest";

import {SearchableSelect} from "@/components/SearchableSelect";

describe("SearchableSelect", () => {
  it("opens a searchable list from a dropdown button", () => {
    render(
      <SearchableSelect
        options={["gpt-4o", "gpt-4o-mini", "claude-3"]}
        value=""
        onChange={() => {}}
        placeholder="Select model"
      />,
    );

    const trigger = screen.getByRole("button", {name: "Select model"});
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("searchbox")).toBeNull();

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    fireEvent.change(screen.getByRole("searchbox", {name: "Search models"}), {target: {value: "MINI"}});
    expect(screen.getByRole("option", {name: "gpt-4o-mini"})).toBeDefined();
    expect(screen.queryByRole("option", {name: "claude-3"})).toBeNull();
  });

  it("selects an option and reports it", () => {
    const onChange = vi.fn();
    render(
      <SearchableSelect
        options={["gpt-4o", "gpt-4o-mini"]}
        value=""
        onChange={onChange}
        placeholder="Select model"
      />,
    );
    fireEvent.click(screen.getByRole("button", {name: "Select model"}));
    fireEvent.change(screen.getByRole("searchbox", {name: "Search models"}), {target: {value: "mini"}});
    fireEvent.click(screen.getByRole("option", {name: "gpt-4o-mini"}));
    expect(onChange).toHaveBeenCalledWith("gpt-4o-mini");
  });

  it("shows the current value in the button", () => {
    render(
      <SearchableSelect options={["a", "b"]} value="a" onChange={() => {}} placeholder="M" />,
    );
    expect(screen.getByRole("button", {name: "a"})).toBeDefined();
  });

  it("typing a non-matching string selects nothing", () => {
    const onChange = vi.fn();
    render(
      <SearchableSelect options={["a", "b"]} value="" onChange={onChange} placeholder="M" />,
    );
    fireEvent.click(screen.getByRole("button", {name: "M"}));
    fireEvent.change(screen.getByRole("searchbox", {name: "Search models"}), {target: {value: "zzz"}});
    expect(screen.queryByRole("option")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });
});
