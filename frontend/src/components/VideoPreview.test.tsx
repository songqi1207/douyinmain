import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { JobResult } from "../types";
import { VideoPreview } from "./VideoPreview";


const result = {
  type: "video",
  url: "/video.mp4",
  poster_url: null,
  downloadable: true,
} as JobResult;


function setVideoSize(video: HTMLVideoElement, width: number, height: number) {
  Object.defineProperties(video, {
    videoWidth: { configurable: true, value: width },
    videoHeight: { configurable: true, value: height },
  });
}


describe("VideoPreview", () => {
  it("uses a portrait player only for portrait media", () => {
    const { container } = render(<VideoPreview jobId="portrait-job" result={result} />);
    const video = container.querySelector("video") as HTMLVideoElement;
    setVideoSize(video, 1080, 1920);
    fireEvent.loadedMetadata(video);

    expect(video).toHaveAttribute("preload", "metadata");
    expect(container.querySelector(".video-preview-shell")).toHaveAttribute("data-orientation", "portrait");
  });

  it("keeps landscape media in a landscape player", () => {
    const { container } = render(<VideoPreview jobId="landscape-job" result={result} />);
    const video = container.querySelector("video") as HTMLVideoElement;
    setVideoSize(video, 1920, 1080);
    fireEvent.loadedMetadata(video);

    expect(container.querySelector(".video-preview-shell")).toHaveAttribute("data-orientation", "landscape");
  });
});
