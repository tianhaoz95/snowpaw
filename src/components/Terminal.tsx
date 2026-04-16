/**
 * Terminal — xterm.js wrapper
 *
 * Renders the full-height terminal pane. The parent passes a ref
 * (writeToTerminalRef) that it uses to inject text from agent events.
 * User keystrokes are accumulated and sent to the agent on Enter.
 * Ctrl-C triggers interrupt.
 */

import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Terminal as XTerm } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { MutableRefObject, useEffect, useRef } from "react";

interface Props {
  onInput: (text: string) => void;
  onInterrupt: () => void;
  modelLoaded: boolean;
  /** Ref that the parent sets to a write function for injecting text. */
  writeToTerminalRef: MutableRefObject<((text: string) => void) | null>;
}

const PROMPT = "\x1b[38;2;255;45;152m❯\x1b[0m ";

export default function Terminal({ onInput, onInterrupt, modelLoaded, writeToTerminalRef }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const inputBufferRef = useRef<string>("");
  const modelLoadedRef = useRef(modelLoaded);
  // Keep ref in sync with prop so the onData closure always sees current value.
  useEffect(() => { modelLoadedRef.current = modelLoaded; }, [modelLoaded]);

  useEffect(() => {
    const term = new XTerm({
      fontFamily: '"JetBrains Mono", "Cascadia Code", "Fira Code", monospace',
      fontSize: 14,
      lineHeight: 1.4,
      theme: {
        background: "#080008",
        foreground: "#ffe0ff",
        cursor: "#ff2d98",
        cursorAccent: "#080008",
        selectionBackground: "#ff2d9855",
        // black / bright-black
        black: "#2a002a",
        brightBlack: "#7a3a7a",
        // red → hot pink
        red: "#ff2d98",
        brightRed: "#ff80c0",
        // green → neon purple
        green: "#dd44ff",
        brightGreen: "#ee88ff",
        // yellow → bright violet
        yellow: "#cc66ff",
        brightYellow: "#dd99ff",
        // blue → medium violet
        blue: "#aa55ff",
        brightBlue: "#cc88ff",
        // magenta → hot pink
        magenta: "#ff2d98",
        brightMagenta: "#ff99cc",
        // cyan → light pink
        cyan: "#ffaadd",
        brightCyan: "#ffddee",
        white: "#dddddd",
        brightWhite: "#ffffff",
      },
      cursorBlink: true,
      scrollback: 5000,
      convertEol: false,
    });

    const fit = new FitAddon();
    term.loadAddon(fit);
    term.loadAddon(new WebLinksAddon());

    if (containerRef.current) {
      term.open(containerRef.current);
      fit.fit();
    }

    // ── Welcome banner ────────────────────────────────────────────────────────
    const P  = "\x1b[38;2;0;255;255m";   // cyber cyan
    const V  = "\x1b[38;2;187;0;255m";    // violet
    const W  = "\x1b[38;2;255;255;255m";  // white
    const DM = "\x1b[2m";                 // dim
    const R  = "\x1b[0m";                 // reset

    const logo = [
      "",
      `${P}   ██████╗██╗   ██╗██████╗ ███████╗██████╗ ██████╗  █████╗ ██╗    ██╗${R}`,
      `${P}  ██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗██╔══██╗██╔══██╗██║    ██║${R}`,
      `${P}  ██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝██████╔╝███████║██║ █╗ ██║${R}`,
      `${P}  ██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗██╔═══╝ ██╔══██║██║███╗██║${R}`,
      `${P}  ╚██████╗   ██║   ██████╔╝███████╗██║  ██║██║     ██║  ██║╚███╔███╔╝${R}`,
      `${P}   ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝ ╚══╝╚══╝${R}`,
      "",
      `${W}                  local coding agent  ${DM}v0.1.0  ·  offline  ·  yours${R}`,
      "",
      `${DM}  Type a task and press Enter.  Ctrl-C to interrupt.${R}`,
      "",
    ];

    for (const line of logo) term.writeln(line);
    term.write(PROMPT);

    termRef.current = term;
    fitRef.current = fit;

    // Expose write function to parent
    writeToTerminalRef.current = (text: string) => {
      term.write(text);
    };

    // Handle user keystrokes
    term.onData((data) => {
      const code = data.charCodeAt(0);

      if (data === "\r") {
        // Enter
        const line = inputBufferRef.current;
        inputBufferRef.current = "";
        term.writeln("");
        if (!modelLoadedRef.current) {
          term.writeln("\x1b[2mNo model loaded — open Settings to load one.\x1b[0m");
          term.write(PROMPT);
        } else if (line.trim()) {
          onInput(line);
        } else {
          term.write(PROMPT);
        }
      } else if (data === "\x03") {
        // Ctrl-C
        inputBufferRef.current = "";
        term.writeln("^C");
        term.write(PROMPT);
        onInterrupt();
      } else if (data === "\x7f" || data === "\b") {
        // Backspace
        if (inputBufferRef.current.length > 0) {
          inputBufferRef.current = inputBufferRef.current.slice(0, -1);
          term.write("\b \b");
        }
      } else if (code >= 32) {
        // Printable character
        inputBufferRef.current += data;
        term.write(data);
      }
    });

    // Resize observer
    const ro = new ResizeObserver(() => {
      fit.fit();
    });
    if (containerRef.current) ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      term.dispose();
      writeToTerminalRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Prompt re-emission is handled in useAgent.ts on status→idle transitions.

  return (
    <div
      ref={containerRef}
      style={{
        flex: 1,
        overflow: "hidden",
        padding: "4px 8px",
      background: "#080008",
        boxSizing: "border-box",
      }}
    />
  );
}
