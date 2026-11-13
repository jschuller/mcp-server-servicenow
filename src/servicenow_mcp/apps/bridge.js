/*
 * McpApp: the view side of MCP Apps (extension io.modelcontextprotocol/ui,
 * protocol 2026-01-26) in one small script, with no dependency and no network
 * access. compose_view() inlines it ahead of a view's own script.
 *
 *   const app = await McpApp.connect({
 *     name: "my-view", version: "1.0.0",
 *     onInput(args) {},        // the tool call's arguments
 *     onResult(result) {},     // the tool's result (a CallToolResult)
 *     onCancelled(reason) {},  // the call was cancelled
 *     onContext(context) {},   // host context, at start and when it changes
 *   });
 *   app.toolName      the tool that opened this view (a mount may rename it)
 *   app.args          the last arguments received
 *   app.canCallTools  whether the host lets the view call server tools
 *   await app.callTool()             the same tool again, same arguments
 *   await app.callTool(name, args)   another tool of the same server
 *
 *   McpApp.data(result)       structuredContent, or the first text block parsed as JSON
 *   McpApp.errorText(result)  the message of an error result, or null
 *   McpApp.text(value)        a field as plain text ({display_value, value} too)
 *   McpApp.el(tag, cls, txt)  a new element; text goes in through textContent
 *
 * It applies the host's theme and style variables to the document and reports
 * the content height, so a view only draws. Text from the instance is
 * untrusted: build elements with McpApp.el and never write it as markup.
 */
const McpApp = (() => {
  "use strict";

  const PROTOCOL_VERSION = "2026-01-26";
  const host = window.parent;

  function data(result) {
    if (result && result.structuredContent && typeof result.structuredContent === "object") {
      return result.structuredContent;
    }
    const first = result && Array.isArray(result.content) ? result.content.find((c) => c.type === "text") : null;
    if (!first) return null;
    try { return JSON.parse(first.text); } catch { return null; }
  }

  function errorText(result) {
    if (!result || !result.isError) return null;
    const first = Array.isArray(result.content) ? result.content.find((c) => c.type === "text") : null;
    return first ? String(first.text) : "The tool returned an error.";
  }

  function text(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "object") return String(value.display_value ?? value.value ?? "");
    return String(value);
  }

  function el(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined && content !== null) node.textContent = String(content);
    return node;
  }

  function applyContext(context) {
    if (!context) return;
    const root = document.documentElement;
    if (context.theme === "light" || context.theme === "dark") root.dataset.theme = context.theme;
    const variables = context.styles && context.styles.variables;
    if (variables && typeof variables === "object") {
      for (const [key, value] of Object.entries(variables)) {
        if (key.startsWith("--") && typeof value === "string") root.style.setProperty(key, value);
      }
    }
  }

  async function connect(options) {
    const handlers = options || {};
    if (host === window) throw new Error("no MCP Apps host: this view has no data on its own");

    // JSON-RPC 2.0 over postMessage. The parent may be the host or its sandbox
    // proxy, on an origin the view cannot know, so messages go to "*" and
    // incoming ones are accepted by source only.
    let nextId = 1;
    const pending = new Map();
    const post = (message) => host.postMessage(message, "*");
    const request = (method, params) => {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        post({ jsonrpc: "2.0", id, method, params: params || {} });
      });
    };
    const notify = (method, params) => post({ jsonrpc: "2.0", method, params: params || {} });

    const app = {
      toolName: null,
      args: {},
      canCallTools: false,
      hostContext: {},
      callTool(name, args) {
        return request("tools/call", { name: name || app.toolName, arguments: args || app.args });
      },
    };

    function useContext(context) {
      if (!context) return;
      Object.assign(app.hostContext, context);
      applyContext(context);
      const tool = context.toolInfo && context.toolInfo.tool;
      if (tool && typeof tool.name === "string") app.toolName = tool.name;
      if (handlers.onContext) handlers.onContext(app.hostContext);
    }

    window.addEventListener("message", (event) => {
      if (event.source !== host) return;
      const message = event.data;
      if (!message || message.jsonrpc !== "2.0") return;

      if (message.method === undefined) {
        const waiter = pending.get(message.id);
        if (!waiter) return;
        pending.delete(message.id);
        if (message.error) waiter.reject(new Error(String(message.error.message || "request failed")));
        else waiter.resolve(message.result);
        return;
      }
      if (message.id !== undefined) {
        // Requests from the host: teardown and ping take an empty result.
        if (message.method === "ui/resource-teardown" || message.method === "ping") {
          post({ jsonrpc: "2.0", id: message.id, result: {} });
        } else {
          post({ jsonrpc: "2.0", id: message.id, error: { code: -32601, message: "Method not found" } });
        }
        return;
      }
      const params = message.params || {};
      switch (message.method) {
        case "ui/notifications/tool-input":
          app.args = params.arguments || {};
          if (handlers.onInput) handlers.onInput(app.args);
          break;
        case "ui/notifications/tool-result":
          if (handlers.onResult) handlers.onResult(params);
          break;
        case "ui/notifications/tool-cancelled":
          if (handlers.onCancelled) handlers.onCancelled(params.reason || "");
          break;
        case "ui/notifications/host-context-changed":
          useContext(params);
          break;
      }
    });

    const result = await request("ui/initialize", {
      protocolVersion: PROTOCOL_VERSION,
      appInfo: { name: handlers.name || "servicenow-view", version: handlers.version || "0.0.0" },
      appCapabilities: { availableDisplayModes: ["inline"] },
    });
    app.canCallTools = Boolean(result && result.hostCapabilities && result.hostCapabilities.serverTools);
    useContext(result && result.hostContext);
    // The host sends the tool input and result only after this notification.
    notify("ui/notifications/initialized");

    let lastHeight = 0;
    const reportSize = () => {
      const height = Math.ceil(document.documentElement.getBoundingClientRect().height);
      if (height && height !== lastHeight) {
        lastHeight = height;
        notify("ui/notifications/size-changed", { height });
      }
    };
    new ResizeObserver(reportSize).observe(document.documentElement);
    reportSize();
    return app;
  }

  return { PROTOCOL_VERSION, connect, data, errorText, text, el };
})();
