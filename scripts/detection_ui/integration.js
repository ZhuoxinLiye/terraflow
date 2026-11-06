'use strict';
// Adapt the user's existing preview UI to the authenticated Earthmind workspace.
const detectionApi = '/api/workspace/detection/api';
const notifyWorkspace = (type, payload = {}) => parent.postMessage({ type, ...payload }, location.origin);
$('token').value = 'workspace-session';
window.addEventListener('earthmind:result-cleared', () => notifyWorkspace('earthmind:detection-cleared'));
notifyWorkspace('earthmind:detection-cleared');

async function savedHistory() {
  const current = $('savedResults').value;
  const data = await (await request(detectionApi + '/history')).json();
  $('savedResults').replaceChildren(new Option('选择已保存检测', ''));
  for (const item of data.results) {
    const title = `${item.registered_at.slice(0, 16).replace('T', ' ')} · ${item.detection_count} 个候选区域`;
    $('savedResults').append(new Option(title, item.dataset_id));
  }
  $('savedResults').value = current;
}

async function showSaved(datasetId) {
  if (busy || !datasetId) return;
  busy = true;
  result = null;
  notifyWorkspace('earthmind:detection-cleared');
  buttons();
  try {
    const data = await (await request(detectionApi + '/result?dataset_id=' + encodeURIComponent(datasetId))).json();
    const rows = await (await request(detectionApi + '/file?path=' + encodeURIComponent(data.artifacts['category_roles.json']))).json();
    const records = await (await request(detectionApi + '/file?path=' + encodeURIComponent(data.artifacts['segearth_candidates.json']))).json();
    const original = data.artifacts['original_preview.png'] || data.image.path;
    const blob = await (await request(detectionApi + '/file?path=' + encodeURIComponent(original))).blob();
    [originalUrl, semanticUrl].filter(Boolean).forEach(url => URL.revokeObjectURL(url));
    file = null;
    originalUrl = URL.createObjectURL(blob);
    semanticUrl = null;
    result = data;
    detections = records;
    resultCategories = rows.filter(row => row.class_id !== 0).sort((a, b) => a.class_id - b.class_id);
    $('preview').src = originalUrl;
    $('count').textContent = data.detection_count;
    $('elapsed').textContent = Number(data.provenance.elapsed_seconds).toFixed(1) + ' s';
    $('filename').textContent = '已保存检测 · ' + datasetId;
    $('view').value = 'boxes';
    overlay = true;
    drawBoxes();
    renderLegend();
    updateOverlay();
    $('useGraph').disabled = false;
    $('progressTitle').textContent = '已保存检测结果';
    $('percent').textContent = '100%';
    $('progressDetail').textContent = '读取已保存产物，不重新运行检测';
    status('结果已载入。数量为模型候选区域；坐标使用原图像素。');
  } catch (error) {
    result = null;
    detections = [];
    drawBoxes();
    status(error.message, 'error');
  } finally {
    busy = false;
    buttons();
  }
}
$('savedResults').onchange = () => void showSaved($('savedResults').value);
$('useGraph').onclick = () => {
  if (!result?.dataset_id) return;
  notifyWorkspace('earthmind:detection-selected', {
    dataset_id: result.dataset_id,
    snapshot_id: result.snapshot_id,
    detection_count: result.detection_count,
  });
  status('已选中当前检测快照，可在上方添加图谱查询节点。');
};
const originalRun = $('run').onclick;
$('run').onclick = async () => {
  notifyWorkspace('earthmind:detection-busy', { busy: true });
  $('savedResults').disabled = true;
  $('useGraph').disabled = true;
  try {
    await originalRun();
    if (result?.dataset_id) {
      $('useGraph').disabled = false;
      await savedHistory();
      $('savedResults').value = result.dataset_id;
    }
  } finally {
    $('savedResults').disabled = false;
    notifyWorkspace('earthmind:detection-busy', { busy: false });
  }
};
void loadPrompts();
void savedHistory().catch(error => status(error.message, 'error'));
