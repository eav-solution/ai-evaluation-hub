import {render, screen} from "@testing-library/react";
import {beforeEach, describe, expect, it, vi} from "vitest";

import {WorkspaceNav} from "@/components/WorkspaceNav";

let pathname = "/w/workspace-1/datasets";

vi.mock("next/link", () => ({
  default: ({children, ...props}: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props}>{children}</a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({push: vi.fn()}),
}));

vi.mock("@/lib/api", () => ({clearToken: vi.fn()}));

describe("WorkspaceNav", () => {
  beforeEach(() => {
    pathname = "/w/workspace-1/datasets";
  });

  it("marks the active workspace destination as the current page", () => {
    render(<WorkspaceNav workspaceId="workspace-1" />);

    expect(screen.getByRole("link", {name: "Datasets"})).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", {name: "Runs"})).not.toHaveAttribute("aria-current");
  });

  it("links to and marks Model Benchmarks as the active workspace destination", () => {
    pathname = "/w/workspace-1/model-benchmarks";
    render(<WorkspaceNav workspaceId="workspace-1" />);

    expect(screen.getByRole("link", {name: "Model Benchmarks"})).toHaveAttribute(
      "href",
      "/w/workspace-1/model-benchmarks",
    );
    expect(screen.getByRole("link", {name: "Model Benchmarks"})).toHaveAttribute("aria-current", "page");
  });
});
