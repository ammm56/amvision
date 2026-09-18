import type { SupportedLocale } from './locales'

/** 节点编辑及结果面板的界面文案；业务标签和状态值不翻译。 */
const english = {
  apply: 'Apply', cancel: 'Cancel', reset: 'Reset to Default', edit: 'Edit', editLabel: 'Edit {label}',
  configured: '{count} configured', unconfigured: 'Not configured', custom: 'Custom', default: 'Default',
  collapse: 'Collapse', expand: 'Expand Results', results: 'Results', partial: 'Summarizing · Partial results',
  moveUp: 'Move up', moveDown: 'Move down', deleteRow: 'Delete row', addRow: 'Add row',
  matchValues: 'Match Values · One value per line', editCondition: 'Edit Condition JSON',
  invalidConfig: 'Please correct the invalid color or state settings', invalidJson: 'Invalid JSON; this field has not been applied',
  chooseColor: 'Choose {label}', resetColor: 'Reset {label}', invalidColor: 'Enter a #RRGGBB color',
  addState: 'Add state', deleteState: 'Delete state', invalidState: 'State values must contain 1–128 characters', duplicateState: 'State values must be unique',
  invalidAppearance: 'Check the color and size ranges. Leave width and height blank for Auto.', appearancePreview: 'Appearance preview',
}
type DisplayMessages = Record<keyof typeof english, string>

export const workflowDisplayMessages: Record<SupportedLocale, DisplayMessages> = {
  'en-US': english,
  'zh-CN': {
    apply: '应用', cancel: '取消', reset: '恢复默认', edit: '编辑', editLabel: '编辑 {label}',
    configured: '已配置 {count} 项', unconfigured: '未配置', custom: '自定义', default: '默认',
    collapse: '收起', expand: '展开结果', results: '结果显示', partial: '汇总中 · 当前为部分结果',
    moveUp: '上移', moveDown: '下移', deleteRow: '删除行', addRow: '添加行',
    matchValues: 'Match Values · 每行一个值', editCondition: '编辑条件 JSON',
    invalidConfig: '请修正无效的颜色或状态配置', invalidJson: 'JSON 格式无效，尚未应用此字段',
    chooseColor: '选择 {label}', resetColor: '{label} 恢复默认', invalidColor: '请输入 #RRGGBB 颜色',
    addState: '添加状态', deleteState: '删除状态', invalidState: '状态值不能为空且不能超过 128 字符', duplicateState: '状态值不能重复',
    invalidAppearance: '请检查颜色和尺寸范围；宽高留空表示 Auto。', appearancePreview: '外观示例',
  },
  'ja-JP': {
    apply: '適用', cancel: 'キャンセル', reset: '既定に戻す', edit: '編集', editLabel: '{label} を編集',
    configured: '{count} 件設定済み', unconfigured: '未設定', custom: 'カスタム', default: '既定',
    collapse: '折りたたむ', expand: '結果を展開', results: '結果表示', partial: '集計中 · 部分的な結果',
    moveUp: '上へ', moveDown: '下へ', deleteRow: '行を削除', addRow: '行を追加',
    matchValues: 'Match Values · 1 行に 1 つの値', editCondition: '条件 JSON を編集',
    invalidConfig: '色または状態の設定を修正してください', invalidJson: 'JSON が無効です。このフィールドは未適用です',
    chooseColor: '{label} を選択', resetColor: '{label} をリセット', invalidColor: '#RRGGBB 形式で色を入力してください',
    addState: '状態を追加', deleteState: '状態を削除', invalidState: '状態値は 1～128 文字で入力してください', duplicateState: '状態値は重複できません',
    invalidAppearance: '色とサイズの範囲を確認してください。幅と高さが空欄の場合は Auto です。', appearancePreview: '外観プレビュー',
  },
  'ko-KR': {
    apply: '적용', cancel: '취소', reset: '기본값 복원', edit: '편집', editLabel: '{label} 편집',
    configured: '{count}개 설정됨', unconfigured: '설정되지 않음', custom: '사용자 지정', default: '기본값',
    collapse: '접기', expand: '결과 펼치기', results: '결과 표시', partial: '집계 중 · 부분 결과',
    moveUp: '위로', moveDown: '아래로', deleteRow: '행 삭제', addRow: '행 추가',
    matchValues: 'Match Values · 한 줄에 값 하나', editCondition: '조건 JSON 편집',
    invalidConfig: '잘못된 색상 또는 상태 설정을 수정하세요', invalidJson: '잘못된 JSON입니다. 이 필드는 적용되지 않았습니다',
    chooseColor: '{label} 선택', resetColor: '{label} 초기화', invalidColor: '#RRGGBB 형식의 색상을 입력하세요',
    addState: '상태 추가', deleteState: '상태 삭제', invalidState: '상태 값은 1–128자여야 합니다', duplicateState: '상태 값은 중복될 수 없습니다',
    invalidAppearance: '색상과 크기 범위를 확인하세요. 너비와 높이를 비우면 Auto가 적용됩니다.', appearancePreview: '모양 미리보기',
  },
}
