import type { SupportedLocale } from './locales'

export const modelConversionSourceMessages: Record<SupportedLocale, Record<string, string>> = {
  'zh-CN': {
    title: '选择转换来源版本', models: '来源模型', versions: '模型版本', search: '搜索模型名称、类型或参数量',
    empty: '暂无可转换的模型版本', noResults: '没有匹配的来源模型', categoryCount: '{count} 个类别',
    checkpointMissing: '缺少 checkpoint', labelsMissing: '未登记类别映射，仅可用于训练初始化', labelsInvalid: '类别映射不合法',
    required: '请选择有效的转换来源版本', emptySelection: '尚未选择转换来源版本', selectionExpired: '来源版本已失效，请重新选择',
  },
  'en-US': {
    title: 'Select Conversion Source', models: 'Source Models', versions: 'Model Versions', search: 'Search model name, type or scale',
    empty: 'No model versions available for conversion', noResults: 'No matching source models', categoryCount: '{count} categories',
    checkpointMissing: 'Checkpoint missing', labelsMissing: 'No label map; training initialization only', labelsInvalid: 'Invalid label map',
    required: 'Select a valid conversion source version', emptySelection: 'No conversion source selected', selectionExpired: 'Source version no longer available; select again',
  },
  'ja-JP': {
    title: '変換元バージョンを選択', models: 'ソースモデル', versions: 'モデルバージョン', search: 'モデル名、種類、サイズを検索',
    empty: '変換可能なモデルバージョンがありません', noResults: '一致するソースモデルがありません', categoryCount: '{count} クラス',
    checkpointMissing: 'checkpoint がありません', labelsMissing: 'クラス情報なし。学習初期化のみ', labelsInvalid: 'クラス情報が無効です',
    required: '有効な変換元バージョンを選択してください', emptySelection: '変換元が未選択です', selectionExpired: '変換元が無効になりました。再選択してください',
  },
  'ko-KR': {
    title: '변환 소스 버전 선택', models: '소스 모델', versions: '모델 버전', search: '모델 이름, 유형, 크기 검색',
    empty: '변환할 수 있는 모델 버전이 없습니다', noResults: '일치하는 소스 모델이 없습니다', categoryCount: '{count}개 클래스',
    checkpointMissing: 'checkpoint 없음', labelsMissing: '클래스 정보 없음. 학습 초기화만 가능', labelsInvalid: '클래스 정보가 잘못되었습니다',
    required: '유효한 변환 소스 버전을 선택하세요', emptySelection: '변환 소스가 선택되지 않았습니다', selectionExpired: '소스 버전이 유효하지 않습니다. 다시 선택하세요',
  },
}
