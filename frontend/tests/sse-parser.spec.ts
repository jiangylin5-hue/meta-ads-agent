import { expect, test } from "@playwright/test";
import { AgentStreamError, SSEParser, parseAgentStreamFrame, readSSEStream, type SSEFrame } from "../lib/api/sse";

test("SSE parser handles CRLF, split frames, heartbeats, multi-line data and unknown events", () => {
  const parser = new SSEParser();
  const frames: SSEFrame[] = [];
  frames.push(...parser.push(": ping\r\n\r\nid: 7\r\nevent: future.event\r\ndata: {\"seq\":7,\r\nda"));
  frames.push(...parser.push("ta: \"turn_id\":\"trace_1\"}\r\n\r\n"));
  frames.push(...parser.finish());

  expect(frames).toHaveLength(1);
  expect(frames[0]).toEqual({
    id: "7",
    event: "future.event",
    data: "{\"seq\":7,\n\"turn_id\":\"trace_1\"}",
  });
  expect(parseAgentStreamFrame(frames[0])).toMatchObject({ event: "future.event", seq: 7, turn_id: "trace_1" });
});

test("SSE parser handles a final event without a trailing blank line", () => {
  const parser = new SSEParser();
  expect(parser.push("event: turn.failed\ndata: {\"seq\":1,\"turn_id\":\"trace_1\"}")).toEqual([]);
  expect(parser.finish()).toEqual([
    { id: "", event: "turn.failed", data: "{\"seq\":1,\"turn_id\":\"trace_1\"}" },
  ]);
});

test("SSE stream decoder preserves Chinese characters split across network chunks", async () => {
  const bytes = new TextEncoder().encode("event: turn.completed\ndata: {\"seq\":2,\"turn_id\":\"trace_中文\",\"response\":{\"reply\":\"已完成\"}}\n\n");
  const splitAt = bytes.indexOf(0xe6) + 1;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes.slice(0, splitAt));
      controller.enqueue(bytes.slice(splitAt));
      controller.close();
    },
  });
  const frames: SSEFrame[] = [];
  await readSSEStream(stream, (frame) => frames.push(frame));

  expect(frames).toHaveLength(1);
  expect(parseAgentStreamFrame(frames[0])).toMatchObject({
    event: "turn.completed",
    seq: 2,
    turn_id: "trace_中文",
  });
});

test("invalid SSE payloads fail with a typed stream error", () => {
  expect(() => parseAgentStreamFrame({ id: "1", event: "turn.started", data: "not-json" })).toThrow(AgentStreamError);
  expect(() => parseAgentStreamFrame({ id: "1", event: "turn.started", data: "{\"turn_id\":\"trace_1\"}" })).toThrow(
    "流式响应缺少序号或 turn_id。",
  );
});
