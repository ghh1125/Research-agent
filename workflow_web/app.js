const state = {
  definitions: new Map(),
  workflow: { nodes: [], edges: [] },
  selectedNodeId: null,
  connectionSource: null,
  runId: null,
  pollTimer: null,
  runStatus: "idle",
  checkpointSignature: null,
};

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(element._timer);
  element._timer = setTimeout(() => element.classList.remove("show"), 2600);
}

async function initialize() {
  const [definitions, workflow] = await Promise.all([
    api("/api/functions"),
    api("/api/examples/research-workflow"),
  ]);
  state.definitions = new Map(definitions.map((item) => [item.type, item]));
  state.workflow = workflow;
  renderPalette();
  renderCanvas();
}

function renderPalette() {
  $("#palette").innerHTML = [...state.definitions.values()].map((item) => `
    <button class="palette-item" type="button" draggable="true" data-node-type="${escapeHtml(item.type)}" title="${escapeHtml(item.description)}">
      ${escapeHtml(item.name)}
    </button>`).join("");
  document.querySelectorAll(".palette-item").forEach((element) => {
    let droppedByPointer = false;
    element.draggable = false;
    element.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("application/x-node-type", element.dataset.nodeType);
    });
    element.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      element.setPointerCapture(event.pointerId);
      const stop = (upEvent) => {
        droppedByPointer = addNodeFromPaletteDrop(element.dataset.nodeType, upEvent.clientX, upEvent.clientY);
        element.removeEventListener("pointerup", stop);
        element.removeEventListener("pointercancel", cancel);
      };
      const cancel = () => {
        element.removeEventListener("pointerup", stop);
        element.removeEventListener("pointercancel", cancel);
      };
      element.addEventListener("pointerup", stop);
      element.addEventListener("pointercancel", cancel);
    });
    element.addEventListener("click", () => {
      if (droppedByPointer) {
        droppedByPointer = false;
        return;
      }
      addNodeAtVisiblePosition(element.dataset.nodeType);
    });
  });
}

function addNodeFromPaletteDrop(nodeType, clientX, clientY) {
  if (isWorkflowLocked()) {
    toast("当前运行使用启动时快照，完成后才能新增节点");
    return false;
  }
  const canvas = $("#canvas");
  const rect = canvas.getBoundingClientRect();
  if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) return false;
  const x = Math.max(10, clientX - rect.left + canvas.scrollLeft - 89);
  const y = Math.max(10, clientY - rect.top + canvas.scrollTop - 43);
  addNode(nodeType, x, y);
  return true;
}

function addNodeAtVisiblePosition(nodeType) {
  if (isWorkflowLocked()) {
    toast("当前运行使用启动时快照，完成后才能新增节点");
    return;
  }
  const canvas = $("#canvas");
  const offset = state.workflow.nodes.length % 5;
  addNode(nodeType, canvas.scrollLeft + 40 + offset * 24, canvas.scrollTop + 330 + offset * 18);
}

function addNode(nodeType, x, y) {
  const id = `${nodeType}-${Date.now()}-${state.workflow.nodes.length}`;
  state.workflow.nodes.push({ id, type: nodeType, x, y, config: {} });
  selectNode(id);
}

function renderCanvas() {
  const layer = $("#node-layer");
  layer.innerHTML = "";
  for (const node of state.workflow.nodes) {
    const definition = state.definitions.get(node.type);
    if (!definition) continue;
    const displayName = node.config?.display_name || definition.name;
    const description = node.config?.description || definition.description;
    const element = document.createElement("article");
    element.className = `workflow-node ${node.id === state.selectedNodeId ? "selected" : ""} ${node.status || ""}`;
    element.dataset.nodeId = node.id;
    element.style.left = `${node.x || 30}px`;
    element.style.top = `${node.y || 30}px`;
    element.title = description;
    element.innerHTML = `
      <button class="port input" type="button" title="连接输入"></button>
      <div class="node-title">${escapeHtml(displayName)}</div>
      <div class="node-type">${escapeHtml(node.type)}</div>
      <button class="node-delete" type="button" title="删除节点">×</button>
      <button class="port output ${state.connectionSource === node.id ? "active" : ""}" type="button" title="连接输出"></button>`;
    element.addEventListener("click", () => selectNode(node.id));
    element.addEventListener("pointerdown", (event) => {
      if (isWorkflowLocked()) return;
      if (event.target.closest("button")) return;
      element.setPointerCapture(event.pointerId);
      const origin = { x: event.clientX, y: event.clientY, left: node.x || 30, top: node.y || 30 };
      const move = (moveEvent) => {
        node.x = Math.max(10, origin.left + moveEvent.clientX - origin.x);
        node.y = Math.max(10, origin.top + moveEvent.clientY - origin.y);
        element.style.left = `${node.x}px`;
        element.style.top = `${node.y}px`;
        renderEdges();
      };
      const stop = () => {
        element.removeEventListener("pointermove", move);
        element.removeEventListener("pointerup", stop);
        element.removeEventListener("pointercancel", stop);
      };
      element.addEventListener("pointermove", move);
      element.addEventListener("pointerup", stop);
      element.addEventListener("pointercancel", stop);
    });
    element.querySelector(".node-delete").addEventListener("click", (event) => {
      event.stopPropagation();
      deleteNode(node.id);
    });
    element.querySelector(".port.output").addEventListener("click", (event) => {
      event.stopPropagation();
      state.connectionSource = node.id;
      $("#cancel-connect").hidden = false;
      renderCanvas();
    });
    element.querySelector(".port.input").addEventListener("click", (event) => {
      event.stopPropagation();
      connectTo(node.id);
    });
    layer.appendChild(element);
  }
  requestAnimationFrame(renderEdges);
}

function renderEdges() {
  const svg = $("#edge-layer");
  svg.innerHTML = "";
  const canvasRect = $("#canvas").getBoundingClientRect();
  for (const edge of state.workflow.edges) {
    const source = document.querySelector(`[data-node-id="${CSS.escape(edge.source)}"] .port.output`);
    const target = document.querySelector(`[data-node-id="${CSS.escape(edge.target)}"] .port.input`);
    if (!source || !target) continue;
    const a = source.getBoundingClientRect();
    const b = target.getBoundingClientRect();
    const x1 = a.left + a.width / 2 - canvasRect.left + $("#canvas").scrollLeft;
    const y1 = a.top + a.height / 2 - canvasRect.top + $("#canvas").scrollTop;
    const x2 = b.left + b.width / 2 - canvasRect.left + $("#canvas").scrollLeft;
    const y2 = b.top + b.height / 2 - canvasRect.top + $("#canvas").scrollTop;
    const bend = Math.max(50, Math.abs(x2 - x1) / 2);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("class", "edge");
    path.setAttribute("d", `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`);
    svg.appendChild(path);
  }
}

$("#canvas").addEventListener("dragover", (event) => event.preventDefault());
$("#canvas").addEventListener("drop", (event) => {
  event.preventDefault();
  if (isWorkflowLocked()) {
    toast("当前运行使用启动时快照，完成后才能编辑画布");
    return;
  }
  const rect = $("#canvas").getBoundingClientRect();
  const nodeType = event.dataTransfer.getData("application/x-node-type");
  const existingId = event.dataTransfer.getData("application/x-existing-node");
  const offset = JSON.parse(event.dataTransfer.getData("application/x-drag-offset") || '{"x":20,"y":20}');
  const x = Math.max(10, event.clientX - rect.left + $("#canvas").scrollLeft - offset.x);
  const y = Math.max(10, event.clientY - rect.top + $("#canvas").scrollTop - offset.y);
  if (nodeType) {
    const id = `${nodeType}-${Date.now()}`;
    state.workflow.nodes.push({ id, type: nodeType, x, y, config: {} });
    selectNode(id);
  } else if (existingId) {
    const node = getNode(existingId);
    node.x = x;
    node.y = y;
    renderCanvas();
  }
});

function getNode(id) {
  return state.workflow.nodes.find((node) => node.id === id);
}

function selectNode(id) {
  state.selectedNodeId = id;
  renderCanvas();
  renderConfig();
}

function deleteNode(id) {
  if (isWorkflowLocked()) {
    toast("当前运行使用启动时快照，完成后才能删除节点");
    return;
  }
  state.workflow.nodes = state.workflow.nodes.filter((node) => node.id !== id);
  state.workflow.edges = state.workflow.edges.filter((edge) => edge.source !== id && edge.target !== id);
  if (state.selectedNodeId === id) state.selectedNodeId = null;
  if (state.connectionSource === id) state.connectionSource = null;
  renderCanvas();
  renderConfig();
}

function connectTo(targetId) {
  if (isWorkflowLocked()) {
    toast("当前运行使用启动时快照，完成后才能修改连线");
    return;
  }
  if (!state.connectionSource || state.connectionSource === targetId) return;
  const exists = state.workflow.edges.some((edge) => edge.source === state.connectionSource && edge.target === targetId);
  if (!exists) state.workflow.edges.push({ source: state.connectionSource, target: targetId });
  state.connectionSource = null;
  $("#cancel-connect").hidden = true;
  renderCanvas();
}

$("#cancel-connect").addEventListener("click", () => {
  state.connectionSource = null;
  $("#cancel-connect").hidden = true;
  renderCanvas();
});

function renderConfig() {
  const container = $("#config-content");
  const node = getNode(state.selectedNodeId);
  if (!node) {
    container.className = "empty-state";
    container.textContent = "选择画布中的节点。";
    return;
  }
  container.className = "";
  const definition = state.definitions.get(node.type);
  node.config ||= {};
  const configFields = definition.configFields.map((field) => configFieldHtml(node, field)).join("");
  const fileFields = definition.fileFields.map((field) => fileFieldHtml(node, field)).join("");
  const llmSteps = (definition.llmSteps || []).map((step) => llmStepHtml(node, step)).join("");
  container.innerHTML = `
    <section class="config-section">
      <h3>基本设置</h3>
      <label class="field">节点名称
        <input data-instance-key="display_name" value="${escapeHtml(node.config.display_name || definition.name)}">
      </label>
      <label class="field">节点描述
        <textarea data-instance-key="description">${escapeHtml(node.config.description || definition.description)}</textarea>
      </label>
      <small class="node-id">${escapeHtml(node.id)} · ${escapeHtml(node.type)}</small>
    </section>
    ${(configFields || fileFields) ? `<section class="config-section"><h3>业务输入</h3>${configFields}${fileFields}</section>` : ""}
    ${llmSteps ? `<section class="config-section"><h3>LLM 设置</h3>${llmSteps}</section>` : ""}
    <div class="config-actions"><button class="danger" id="delete-selected" type="button">删除此节点</button></div>`;
  container.querySelectorAll("[data-instance-key]").forEach((input) => {
    input.addEventListener("input", () => {
      const key = input.dataset.instanceKey;
      const defaultValue = key === "display_name" ? definition.name : definition.description;
      if (input.value === defaultValue) delete node.config[key];
      else node.config[key] = input.value;
      const canvasNode = document.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`);
      if (canvasNode && key === "display_name") canvasNode.querySelector(".node-title").textContent = input.value || definition.name;
      if (canvasNode && key === "description") canvasNode.title = input.value || definition.description;
    });
  });
  container.querySelectorAll("[data-config-key]").forEach((input) => {
    input.addEventListener("input", () => { node.config[input.dataset.configKey] = input.value; });
  });
  container.querySelectorAll("[data-file-key]").forEach((input) => {
      input.addEventListener("change", () => uploadNodeFiles(node, input.dataset.fileKey, input.files));
  });
  container.querySelectorAll("[data-llm-model]").forEach((input) => {
    input.addEventListener("change", () => {
      const step = ensureLLMStepConfig(node, input.dataset.llmModel);
      step.model = input.value;
    });
  });
  container.querySelectorAll("[data-llm-prompt]").forEach((input) => {
    input.addEventListener("input", () => {
      const step = ensureLLMStepConfig(node, input.dataset.llmPrompt);
      step.prompt = input.value;
    });
  });
  container.querySelectorAll("[data-restore-llm]").forEach((button) => {
    button.addEventListener("click", () => {
      if (node.config.llm_steps) {
        delete node.config.llm_steps[button.dataset.restoreLlm];
        if (!Object.keys(node.config.llm_steps).length) delete node.config.llm_steps;
      }
      renderConfig();
    });
  });
  $("#delete-selected").addEventListener("click", () => deleteNode(node.id));
}

function ensureLLMStepConfig(node, stepId) {
  node.config.llm_steps ||= {};
  node.config.llm_steps[stepId] ||= {};
  return node.config.llm_steps[stepId];
}

function llmStepHtml(node, step) {
  const configured = node.config?.llm_steps?.[step.id] || {};
  const model = configured.model || step.defaultModel;
  const prompt = configured.prompt ?? step.defaultPrompt;
  const modelOptions = step.models.map((item) => `
    <option value="${escapeHtml(item)}" ${item === model ? "selected" : ""}>${escapeHtml(item)}</option>`).join("");
  const variableHelp = (step.variableHelp || []).map((item) => `
    <li>
      <code>${escapeHtml(item.placeholder)}</code>
      <span>${escapeHtml(item.description)}</span>
      <small>材料来源：${escapeHtml(item.source)}</small>
    </li>`).join("");
  return `<details class="llm-step">
    <summary>${escapeHtml(step.name)}</summary>
    <label class="field">模型
      <select data-llm-model="${escapeHtml(step.id)}">${modelOptions}</select>
    </label>
    <label class="field">Prompt
      <textarea class="prompt-editor" data-llm-prompt="${escapeHtml(step.id)}">${escapeHtml(prompt)}</textarea>
    </label>
    <div class="prompt-variable-help">
      <strong>可用变量与材料对应关系</strong>
      ${variableHelp
        ? `<p>把下列变量写入或保留在 Prompt 中，运行时会自动替换为对应材料，不需要手工粘贴材料内容。</p><ul>${variableHelp}</ul>`
        : "<p>此 Prompt 没有可插入的材料变量。</p>"}
      <p>示例：<code>请根据 {bp_text} 分析项目。</code> 如果需要输出字面花括号，请写成 <code>{{</code> 和 <code>}}</code>。</p>
    </div>
    <button type="button" data-restore-llm="${escapeHtml(step.id)}">恢复默认 Prompt</button>
  </details>`;
}

function configFieldHtml(node, field) {
  const value = node.config?.[field.key] || "";
  let control;
  if (field.kind === "textarea") {
    control = `<textarea data-config-key="${escapeHtml(field.key)}">${escapeHtml(value)}</textarea>`;
  } else if (field.kind === "select") {
    control = `<select data-config-key="${escapeHtml(field.key)}"><option value="">请选择</option>${
      field.options.map((option) => `<option ${value === option ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")
    }</select>`;
  } else {
    control = `<input data-config-key="${escapeHtml(field.key)}" value="${escapeHtml(value)}">`;
  }
  return `<label class="field">${escapeHtml(field.label)}${field.required ? " *" : ""}${control}</label>`;
}

function fileFieldHtml(node, field) {
  const files = node.config?.[field.key] || [];
  return `<label class="field">${escapeHtml(field.label)}
    <input type="file" data-file-key="${escapeHtml(field.key)}" accept="${escapeHtml(field.accept.join(","))}" ${field.multiple ? "multiple" : ""}>
    <span class="upload-list">${files.length ? files.map(escapeHtml).join("<br>") : "未上传"}</span>
  </label>`;
}

async function uploadNodeFiles(node, key, fileList) {
  try {
    const files = await Promise.all([...fileList].map(async (file) => ({
      name: file.name,
      content: await fileToBase64(file),
    })));
    const response = await api("/api/uploads", { method: "POST", body: JSON.stringify({ files }) });
    node.config[key] = response.files.map((item) => item.path);
    renderConfig();
    toast(`已上传 ${response.files.length} 个文件`);
  } catch (error) {
    toast(error.message);
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function loadDefault() {
  if (isWorkflowLocked()) {
    toast("当前运行使用启动时快照，完成后才能重置画布");
    return;
  }
  state.workflow = await api("/api/examples/research-workflow");
  state.selectedNodeId = null;
  state.connectionSource = null;
  renderCanvas();
  renderConfig();
}

async function validateCurrent(showSuccess = true) {
  const result = await api("/api/workflows/validate", {
    method: "POST",
    body: JSON.stringify({ workflow: state.workflow }),
  });
  if (showSuccess) toast(`校验通过，共 ${result.order.length} 个节点`);
  return result;
}

async function runWorkflow() {
  const button = $("#run-workflow");
  try {
    button.disabled = true;
    await validateCurrent(false);
    const response = await api("/api/runs", {
      method: "POST",
      body: JSON.stringify({
        workflow: state.workflow,
        apiKeys: {
          dashscopeApiKey: $("#dashscope-key").value,
          serperApiKey: $("#serper-key").value,
        },
      }),
    });
    state.runId = response.runId;
    state.runStatus = "queued";
    state.checkpointSignature = null;
    setWorkflowLocked(true);
    $("#run-summary").textContent = `运行 ${state.runId.slice(0, 8)} 已启动`;
    clearInterval(state.pollTimer);
    state.pollTimer = setInterval(pollRun, 800);
    await pollRun();
  } catch (error) {
    toast(error.message);
    button.disabled = false;
  }
}

async function pollRun() {
  if (!state.runId) return;
  try {
    const run = await api(`/api/runs/${state.runId}`);
    state.runStatus = run.status;
    $("#run-summary").textContent = `状态：${run.status}`;
    applyNodeStatuses(run.nodes || []);
    setWorkflowLocked(["queued", "running", "waiting"].includes(run.status));
    renderNodeStatuses(run.nodes || []);
    if (run.status === "waiting") {
      const signature = JSON.stringify(run.checkpoint);
      if (signature !== state.checkpointSignature) {
        state.checkpointSignature = signature;
        renderCheckpoint(run.checkpoint);
      }
    } else {
      state.checkpointSignature = null;
      $("#checkpoint-panel").hidden = true;
    }
    if (run.result) renderReports(run.result.state || {});
    if (["completed", "failed"].includes(run.status)) {
      clearInterval(state.pollTimer);
      $("#run-workflow").disabled = false;
      setWorkflowLocked(false);
    }
  } catch (error) {
    clearInterval(state.pollTimer);
    state.runStatus = "failed";
    $("#run-workflow").disabled = false;
    setWorkflowLocked(false);
    toast(error.message);
  }
}

function isWorkflowLocked() {
  return ["queued", "running", "waiting"].includes(state.runStatus);
}

function setWorkflowLocked(locked) {
  document.body.classList.toggle("workflow-locked", locked);
  $("#snapshot-notice").hidden = !locked;
  $("#load-default").disabled = locked;
  document.querySelectorAll(
    "#palette button, #canvas button, #config-panel input, #config-panel select, #config-panel textarea, #config-panel button",
  ).forEach((element) => {
    element.disabled = locked;
  });
}

function applyNodeStatuses(statuses) {
  const statusMap = new Map(statuses.map((item) => [item.nodeId, item.status]));
  state.workflow.nodes.forEach((node) => { node.status = statusMap.get(node.id) || ""; });
  renderCanvas();
}

function renderNodeStatuses(statuses) {
  $("#node-statuses").innerHTML = statuses.map((item) => `
    <div class="status-row"><strong>${escapeHtml(item.status)}</strong>${escapeHtml(item.name)}
    ${item.error ? `<div>${escapeHtml(item.error)}</div>` : ""}
    ${item.missingInputs?.length ? `<div>缺少：${escapeHtml(item.missingInputs.join("、"))}</div>` : ""}</div>`).join("");
}

function renderCheckpoint(checkpoint) {
  if (!checkpoint) return;
  const panel = $("#checkpoint-panel");
  const content = $("#checkpoint-content");
  panel.hidden = false;
  if (checkpoint.checkpoint === "competitor_selection") {
    const discovery = checkpoint.outputs.competitor_discovery;
    content.innerHTML = `<p class="guidance">选择需要进入矩阵分析的竞品。可以全部取消；系统会生成明确的跳过说明。</p>
      <div>${(discovery.candidates || []).map((candidate) => `
        <label class="candidate"><input type="checkbox" data-candidate-id="${escapeHtml(candidate.id)}" checked>
        <span><strong>${escapeHtml(candidate.name)}</strong><br>${escapeHtml(candidate.relationship)} · ${escapeHtml(candidate.product_or_service)}</span></label>`).join("")}</div>
      <div class="checkpoint-actions"><button class="primary" id="submit-selection" type="button">确认选择并继续</button></div>`;
    $("#submit-selection").addEventListener("click", () => {
      const selectedIds = [...content.querySelectorAll("[data-candidate-id]:checked")].map((input) => input.dataset.candidateId);
      resume({ action: "select", selected_ids: selectedIds });
    });
    return;
  }

  const output = Object.values(checkpoint.outputs || {})[0] || {};
  const report = output.markdown || JSON.stringify(output, null, 2);
  const competitor = checkpoint.checkpoint === "competitor_report_review";
  content.innerHTML = `
    <div class="report"><pre>${escapeHtml(report)}</pre></div>
    <p class="guidance">${competitor
      ? "审核不通过时，请写明修改对象、当前问题、期望修改和证据线索。重新汇总不搜索；重新分析全部竞品会重新逐家检索和分析。"
      : "需要修改时，请指出具体章节、错误内容、期望结果和可核验线索；系统只按这条反馈重生成当前节点。"
    }</p>
    <textarea id="review-feedback" placeholder="例如：公司注册信息缺少来源，请核对成立时间并补充来源。"></textarea>
    <div class="checkpoint-actions">
      <button class="primary" id="approve-checkpoint" type="button">确认并继续</button>
      ${competitor
        ? '<button id="resynthesize" type="button">按反馈重新汇总</button><button id="reanalyze" type="button">按反馈重新分析全部竞品</button>'
        : '<button id="regenerate" type="button">按反馈重新生成</button>'}
    </div>`;
  $("#approve-checkpoint").addEventListener("click", () => resume({ action: "approve" }));
  for (const action of competitor ? ["resynthesize", "reanalyze"] : ["regenerate"]) {
    $(`#${action}`).addEventListener("click", () => {
      const feedback = $("#review-feedback").value.trim();
      if (!feedback) return toast("请先填写具体审核意见");
      resume({ action, feedback });
    });
  }
}

async function resume(decision) {
  try {
    await api(`/api/runs/${state.runId}/resume`, { method: "POST", body: JSON.stringify(decision) });
    $("#checkpoint-panel").hidden = true;
    await pollRun();
  } catch (error) {
    toast(error.message);
  }
}

function renderReports(resultState) {
  const reports = Object.entries(resultState)
    .filter(([, value]) => value && typeof value === "object" && typeof value.markdown === "string")
    .map(([key, value]) => `<section class="report"><h3>${escapeHtml(key)}</h3><pre>${escapeHtml(value.markdown)}</pre></section>`);
  $("#report-content").className = reports.length ? "" : "empty-state";
  $("#report-content").innerHTML = reports.length ? reports.join("") : "当前运行没有产生报告。";
}

$("#load-default").addEventListener("click", () => loadDefault().catch((error) => toast(error.message)));
$("#validate-workflow").addEventListener("click", () => validateCurrent().catch((error) => toast(error.message)));
$("#run-workflow").addEventListener("click", runWorkflow);
window.addEventListener("resize", renderEdges);
initialize().catch((error) => toast(error.message));
