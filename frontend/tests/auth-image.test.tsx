import {render, screen, waitFor} from "@testing-library/react";
import {beforeEach, describe, expect, it, vi} from "vitest";

import {AuthImage} from "@/components/AuthImage";
import {getToken} from "@/lib/api";

vi.mock("@/lib/api", () => ({getToken: vi.fn()}));

const mockedGetToken = vi.mocked(getToken);

function response(ok: boolean) {
  return {
    ok,
    status: ok ? 200 : 404,
    blob: () => Promise.resolve(new Blob(["image"])),
  };
}

describe("AuthImage", () => {
  beforeEach(() => {
    mockedGetToken.mockReturnValue("asset-token");
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:asset"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("fetches with the bearer token and revokes the object URL on unmount", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(true));
    vi.stubGlobal("fetch", fetchMock);
    const {unmount} = render(<AuthImage path="/api/assets/asset-1" alt="Chart" />);

    expect(screen.getByText("Loading image…")).toBeInTheDocument();
    expect(await screen.findByRole("img", {name: "Chart"})).toHaveAttribute(
      "src",
      "blob:asset",
    );
    expect(fetchMock).toHaveBeenCalledWith("/api/assets/asset-1", {
      headers: {Authorization: "Bearer asset-token"},
    });

    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:asset");
  });

  it("shows a fallback when the asset response is not OK", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(false)));

    render(<AuthImage path="/api/assets/missing" alt="Missing" />);

    expect(await screen.findByText("Image unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("clears stale images and failures whenever the path changes", async () => {
    let resolveThird!: (value: ReturnType<typeof response>) => void;
    const third = new Promise<ReturnType<typeof response>>((resolve) => {
      resolveThird = resolve;
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(true))
      .mockResolvedValueOnce(response(false))
      .mockReturnValueOnce(third);
    vi.stubGlobal("fetch", fetchMock);
    const {rerender} = render(<AuthImage path="/api/assets/first" alt="Result" />);
    await screen.findByRole("img", {name: "Result"});

    rerender(<AuthImage path="/api/assets/missing" alt="Result" />);
    expect(await screen.findByText("Image unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:asset");

    rerender(<AuthImage path="/api/assets/third" alt="Result" />);
    expect(screen.getByText("Loading image…")).toBeInTheDocument();
    expect(screen.queryByText("Image unavailable")).not.toBeInTheDocument();

    resolveThird(response(true));
    await waitFor(() => expect(screen.getByRole("img", {name: "Result"})).toBeInTheDocument());
  });
});
