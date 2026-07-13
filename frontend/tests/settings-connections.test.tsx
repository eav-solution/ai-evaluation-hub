import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {beforeEach, describe, expect, it, vi} from "vitest";

import {SettingsPanel} from "@/components/SettingsPanel";
import {api} from "@/lib/api";

vi.mock("@/lib/api", () => ({api: vi.fn()}));

const mockedApi = vi.mocked(api);

function routeApi(overrides: {post?: () => Promise<unknown>} = {}) {
  mockedApi.mockImplementation((path: string, init?: RequestInit) => {
    if (path.endsWith("/provider-connections") && (!init || init.method === undefined)) {
      return Promise.resolve([
        {
          id: "c1",
          name: "OpenAI",
          connection_type: "openai",
          base_url: null,
          has_key: true,
          key_hint: "…1234",
        },
      ]) as never;
    }
    if (path.endsWith("/members")) {
      return Promise.resolve([]) as never;
    }
    if (init?.method === "POST" && overrides.post) {
      return overrides.post() as never;
    }
    return Promise.resolve({}) as never;
  });
}

describe("SettingsPanel connections", () => {
  beforeEach(() => {
    mockedApi.mockReset();
  });

  it("lists existing connections", async () => {
    routeApi();
    render(<SettingsPanel workspaceId="ws-1" />);
    await waitFor(() => expect(screen.getByText("OpenAI")).toBeDefined());
    expect(screen.getByText(/Provider connections/i)).toBeDefined();
  });

  it("reveals custom fields when the custom type is chosen", async () => {
    routeApi();
    render(<SettingsPanel workspaceId="ws-1" />);
    await waitFor(() => expect(screen.getByText("OpenAI")).toBeDefined());

    // native default: an API key field is shown
    expect(screen.getByPlaceholderText(/API key/i)).toBeDefined();

    fireEvent.change(screen.getByLabelText(/Connection type/i), {
      target: {value: "openai_compatible"},
    });
    expect(screen.getByPlaceholderText(/Base URL/i)).toBeDefined();
    expect(screen.getByPlaceholderText(/Connection name/i)).toBeDefined();
    expect(screen.getByText(/host\.docker\.internal/i)).toBeDefined();
  });

  it("keeps entered values and shows the error when verification fails", async () => {
    routeApi({post: () => Promise.reject(new Error("The endpoint is not OpenAI-compatible"))});
    render(<SettingsPanel workspaceId="ws-1" />);
    await waitFor(() => expect(screen.getByText("OpenAI")).toBeDefined());

    fireEvent.change(screen.getByLabelText(/Connection type/i), {
      target: {value: "openai_compatible"},
    });
    fireEvent.change(screen.getByPlaceholderText(/Connection name/i), {
      target: {value: "My Gateway"},
    });
    fireEvent.change(screen.getByPlaceholderText(/Base URL/i), {
      target: {value: "http://localhost:11434/v1"},
    });
    fireEvent.click(screen.getByRole("button", {name: /Save connection/i}));

    await waitFor(() =>
      expect(screen.getByText(/not OpenAI-compatible/i)).toBeDefined(),
    );
    // entered values preserved
    expect((screen.getByPlaceholderText(/Base URL/i) as HTMLInputElement).value).toBe(
      "http://localhost:11434/v1",
    );
    expect((screen.getByPlaceholderText(/Connection name/i) as HTMLInputElement).value).toBe(
      "My Gateway",
    );
  });
});
