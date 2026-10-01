export function checkImportScope(data: unknown, scope: 'line'|'song'): void {
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('请粘贴完整的导演 JSON 对象');
  const version = (data as {version?:unknown}).version;
  if (scope === 'line' && version === 'motion-plan-v1') throw new Error('收到的是整曲方案（motion-plan-v1），当前范围为“当前句”。若要导入整曲，请将“方案范围”改为“整曲”后重新校验；若只修改一句，请使用当前句提示词，让 LLM 返回 motion-line-response-v1。尚未保存或应用。');
  if (scope === 'song' && version === 'motion-line-response-v1') throw new Error('收到的是单句方案（motion-line-response-v1），当前范围为“整曲”。请将“方案范围”改为“当前句”，并选择对应歌词后重新校验。尚未保存或应用。');
  if (version !== 'motion-plan-v1' && version !== 'motion-line-response-v1') throw new Error('不支持的导演返回版本，请使用当前页面生成的提示词并保留 output_schema 指定的 version。');
}
