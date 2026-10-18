export type SSEFrame = {
  id: string;
  event: string;
  data: string;
};

export type AgentStreamEvent = {
  event: string;
  seq: number;
  turn_id: string;
  data: Record<string, unknown>;
};

export class AgentStreamError extends Error {
  code: string;
  retryable: boolean;
  turnId: string;

  constructor(code: string, message: string, retryable = false, turnId = "") {
    super(message);
    this.name = "AgentStreamError";
    this.code = code;
    this.retryable = retryable;
    this.turnId = turnId;
  }
}

export class SSEParser {
  private buffer = "";
  private eventName = "";
  private dataLines: string[] = [];
  private lastId = "";
  private firstChunk = true;

  push(chunk: string): SSEFrame[] {
    if (this.firstChunk) {
      this.firstChunk = false;
      if (chunk.startsWith("\ufeff")) chunk = chunk.slice(1);
    }
    this.buffer += chunk;
    const frames: SSEFrame[] = [];

    while (this.buffer.length) {
      const match = /(?:\r\n|\r|\n)/.exec(this.buffer);
      if (!match) break;
      if (match[0] === "\r" && match.index === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      const frame = this.processLine(line);
      if (frame) frames.push(frame);
    }
    return frames;
  }

  finish(): SSEFrame[] {
    const frames: SSEFrame[] = [];
    if (this.buffer) {
      const frame = this.processLine(this.buffer.endsWith("\r") ? this.buffer.slice(0, -1) : this.buffer);
      this.buffer = "";
      if (frame) frames.push(frame);
    }
    const pending = this.dispatch();
    if (pending) frames.push(pending);
    return frames;
  }

  reset(): void {
    this.buffer = "";
    this.eventName = "";
    this.dataLines = [];
    this.lastId = "";
    this.firstChunk = true;
  }

  private processLine(line: string): SSEFrame | null {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return null;

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") this.eventName = value;
    if (field === "data") this.dataLines.push(value);
    if (field === "id" && !value.includes("\u0000")) this.lastId = value;
    return null;
  }

  private dispatch(): SSEFrame | null {
    if (!this.dataLines.length && !this.eventName) return null;
    const frame = {
      id: this.lastId,
      event: this.eventName || "message",
      data: this.dataLines.join("\n"),
    };
    this.eventName = "";
    this.dataLines = [];
    return frame;
  }
}

export async function readSSEStream(
  stream: ReadableStream<Uint8Array>,
  onFrame: (frame: SSEFrame) => void,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        for (const frame of parser.push(decoder.decode())) onFrame(frame);
        for (const frame of parser.finish()) onFrame(frame);
        return;
      }
      for (const frame of parser.push(decoder.decode(value, { stream: true }))) onFrame(frame);
    }
  } finally {
    reader.releaseLock();
  }
}

export function parseAgentStreamFrame(frame: SSEFrame): AgentStreamEvent {
  let payload: unknown;
  try {
    payload = frame.data ? JSON.parse(frame.data) : {};
  } catch {
    throw new AgentStreamError("invalid_event", "流式响应包含无效数据。", false, frame.id);
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new AgentStreamError("invalid_event", "流式响应格式不正确。", false, frame.id);
  }
  const data = payload as Record<string, unknown>;
  const seq = Number(data.seq);
  const turnId = String(data.turn_id || "");
  if (!Number.isInteger(seq) || seq < 1 || !turnId) {
    throw new AgentStreamError("invalid_event", "流式响应缺少序号或 turn_id。", false, turnId);
  }
  return { event: frame.event, seq, turn_id: turnId, data };
}
