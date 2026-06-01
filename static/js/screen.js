// ── TomSelect 자동완성 (300ms debounce) ───────────────────────
let _searchTimer = null;

const tickerSelect = new TomSelect('#ticker-select', {
  valueField: 'symbol',
  labelField: 'symbol',
  searchField: ['symbol', 'name'],
  maxItems: 20,
  create: true,
  createOnBlur: false,
  persist: false,
  placeholder: '예: AAPL MSFT NVDA',
  load(query, callback) {
    if (!query || query.length < 1) return callback();
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
      fetch(`/api/tickers?q=${encodeURIComponent(query)}`)
        .then(r => r.json())
        .then(data => callback(data))
        .catch(() => callback());
    }, 300);
  },
  render: {
    option: (d, escape) =>
      `<div>
        <strong>${escape(d.symbol)}</strong>
        <span class="ts-name">${escape(d.name || '')}</span>
      </div>`,
    item: (d, escape) => `<div>${escape(d.symbol)}</div>`,
  },
});

function toggleAdvanced() {
  const panel = document.getElementById('advanced-settings');
  const arrow = document.getElementById('advanced-arrow');
  const open  = panel.style.display !== 'none';
  panel.style.display = open ? 'none' : 'block';
  arrow.textContent   = open ? '▼' : '▲';
}

// ── 폼 제출 / SSE 스트리밍 ────────────────────────────────────

let _evtSource = null;

document.getElementById('screen-form').addEventListener('submit', function (e) {
  e.preventDefault();

  const values     = tickerSelect.getValue();
  const tickers    = (Array.isArray(values) ? values : [values]).filter(Boolean).join(',');
  const gradeFilter = document.getElementById('grade-filter').value;
  const rsiMin     = document.getElementById('rsi-min').value;
  const rsiMax     = document.getElementById('rsi-max').value;
  const target1    = document.getElementById('target-1').value;
  const target2    = document.getElementById('target-2').value;
  const stopLoss   = document.getElementById('stop-loss').value;
  const includePenny = document.getElementById('include-penny')?.checked ? '1' : '';

  const allChecks  = ['ma_alignment', 'rsi', 'volume', 'macd', 'support', 'bollinger', 'trend'];
  const checked    = Array.from(document.querySelectorAll('input[name="checks"]:checked')).map(el => el.value);
  const allSelected = checked.length === allChecks.length;

  const resultArea = document.getElementById('result-area');
  const submitBtn  = document.getElementById('submit-btn');

  if (_evtSource) { _evtSource.close(); _evtSource = null; }

  submitBtn.disabled  = true;
  submitBtn.textContent = '분석 중...';
  resultArea.innerHTML  = '<div class="polling"><p class="status-text">⏳ 분석 준비 중...</p></div>';
  document.getElementById('screen-filter-bar').style.display = 'none';

  const params = new URLSearchParams();
  if (tickers)      params.set('tickers', tickers);
  if (gradeFilter)  params.set('grade_filter', gradeFilter);
  if (includePenny) params.set('include_penny', 'true');
  params.set('rsi_min',   rsiMin);
  params.set('rsi_max',   rsiMax);
  params.set('target_1',  target1);
  params.set('target_2',  target2);
  params.set('stop_loss', stopLoss);
  if (!allSelected) params.set('checks', checked.join(','));

  _evtSource = new EventSource(`/stream/screen?${params}`);

  function finish() {
    submitBtn.disabled  = false;
    submitBtn.textContent = '▶ RUN SCAN';
  }

  // 진행 상황 텍스트
  _evtSource.addEventListener('progress', function (e) {
    const data = JSON.parse(e.data);
    const polling = resultArea.querySelector('.polling');
    if (polling) polling.querySelector('.status-text').textContent = `⏳ ${data.stage}`;
  });

  // 요약 + 결과 컨테이너 초기화
  _evtSource.addEventListener('init', function (e) {
    const { summary: s } = JSON.parse(e.data);
    document.getElementById('screen-meta').textContent =
      `총 ${s.total}개 분석 | SKIP ${s.skipped}개 | 표시 ${s.displayed}개`;
    resultArea.innerHTML = '<div class="result-container" id="cards-container"></div>';
    document.getElementById('screen-filter-bar').style.display = 'flex';
  });

  // 카드 한 장씩 추가
  _evtSource.addEventListener('card', function (e) {
    const { html } = JSON.parse(e.data);
    const container = document.getElementById('cards-container');
    if (!container) return;
    container.insertAdjacentHTML('beforeend', html);
    // 현재 활성 필터 즉시 적용
    const activeGrade = document.querySelector('#screen-filter-bar .pill.is-active')?.dataset.grade || '';
    if (activeGrade) {
      const newCard = container.lastElementChild;
      const cardGrade = newCard.querySelector('.gt-letter')?.textContent || '';
      if (cardGrade !== activeGrade) newCard.style.display = 'none';
    }
    _markWatchlistBtns();
  });

  // extras 업데이트 (fundamentals 섹션 교체)
  _evtSource.addEventListener('extras', function (e) {
    const { ticker, html } = JSON.parse(e.data);
    if (!ticker || !html) return;

    // 카드 DOM 업데이트 (나중에 모달 열 때 사용)
    const card = document.querySelector(`#result-area [data-ticker="${ticker}"]`);
    if (card) {
      const existing = card.querySelector('.fundamentals-details');
      if (existing) existing.outerHTML = html;
    }

    // 해당 티커로 모달이 열려 있으면 모달 안도 즉시 업데이트
    if (_currentTicker === ticker) {
      const modalFund = document.querySelector('#modal-detail .fundamentals-details');
      if (modalFund) modalFund.outerHTML = html;
    }
  });

  // 결과 없음
  _evtSource.addEventListener('empty', function () {
    resultArea.innerHTML =
      '<p style="color:var(--text-faint);text-align:center;padding:3rem;font-family:var(--font-mono);font-size:12px;">조건에 맞는 종목이 없습니다.</p>';
  });

  // 완료
  _evtSource.addEventListener('done', function () {
    _evtSource.close();
    _evtSource = null;
    finish();
    _markWatchlistBtns();
  });

  // 에러
  _evtSource.addEventListener('error', function (e) {
    _evtSource.close();
    _evtSource = null;
    finish();
    try {
      const data = JSON.parse(e.data);
      resultArea.innerHTML = `<div class="error-box"><p>❌ 오류: ${data.message}</p></div>`;
    } catch {
      // SSE 연결 에러 (파싱 불가) → 무시
    }
  });

  _evtSource.onerror = function () {
    if (_evtSource && _evtSource.readyState === EventSource.CLOSED) {
      finish();
      if (resultArea.querySelector('.polling')) {
        resultArea.innerHTML = '<div class="error-box"><p>❌ 서버 연결이 끊겼습니다.</p></div>';
      }
    }
  };
});

// ── 필터 Pills ────────────────────────────────────────────────

document.querySelectorAll('#screen-filter-bar .pill').forEach(btn => {
  btn.addEventListener('click', function () {
    const grade = this.dataset.grade;
    document.querySelectorAll('#screen-filter-bar .pill').forEach(b => b.classList.remove('is-active'));
    this.classList.add('is-active');
    document.querySelectorAll('#result-area .stock-card').forEach(card => {
      const cardGrade = card.querySelector('.gt-letter')?.textContent || '';
      card.style.display = (!grade || cardGrade === grade) ? '' : 'none';
    });
  });
});

// ── Watchlist 브리지 ──────────────────────────────────────────

let _watchlistSet = new Set();

(async function () {
  try {
    const res  = await fetch('/api/watchlist');
    const data = await res.json();
    _watchlistSet = new Set(data.tickers);
  } catch {}
})();

function _markWatchlistBtns() {
  document.querySelectorAll('.watchlist-btn').forEach(btn => {
    const ticker = btn.dataset.ticker;
    if (_watchlistSet.has(ticker)) {
      btn.classList.add('wl-added');
      btn.title = '관심종목에 추가됨';
    } else {
      btn.classList.remove('wl-added');
    }
  });
}

document.addEventListener('click', async function (e) {
  const btn = e.target.closest('.watchlist-btn');
  if (!btn) return;
  const ticker = btn.dataset.ticker;

  if (btn.classList.contains('wl-added')) {
    try {
      await fetch(`/api/watchlist/${ticker}`, { method: 'DELETE' });
      _watchlistSet.delete(ticker);
      btn.classList.remove('wl-added');
      btn.title = '관심종목에 추가';
    } catch {}
    return;
  }

  try {
    await fetch(`/api/watchlist/${ticker}`, { method: 'POST' });
    _watchlistSet.add(ticker);
    btn.classList.add('wl-added');
    btn.title = '관심종목에 추가됨';
    btn.classList.remove('wl-pop');
    void btn.offsetWidth;
    btn.classList.add('wl-pop');
  } catch {}
});

// ── 차트 모달 ─────────────────────────────────────────────────

let _lwChart     = null;
let _candleSeries = null;
let _allMarkers  = [];
let _currentTicker = null;

document.addEventListener('click', function (e) {
  const btn = e.target.closest('.chart-btn');
  if (!btn) return;
  const card = btn.closest('.stock-card') || btn.closest('.signal-card');
  if (!card) return;
  _openModal(card);
});

function _openModal(card) {
  const ticker = card.dataset.ticker;
  const detail = card.querySelector('.card-detail');
  _currentTicker = ticker;

  document.getElementById('modal-ticker').textContent  = ticker;
  document.getElementById('modal-detail').innerHTML    = detail ? detail.innerHTML : '';
  const company = card.querySelector('.short-name')?.textContent || '';
  document.getElementById('modal-company').textContent = company;

  document.getElementById('chart-modal').classList.add('is-open');
  _fetchAndRenderChart(ticker);
}

function _closeModal() {
  document.getElementById('chart-modal').classList.remove('is-open');
  if (_lwChart) {
    _lwChart.remove();
    _lwChart = null;
    _candleSeries = null;
    _allMarkers   = [];
    _currentTicker = null;
  }
}

async function _fetchAndRenderChart(ticker) {
  const container = document.getElementById('lw-chart-container');
  container.innerHTML = '<p style="color:var(--text3);padding:1rem;text-align:center">차트 로딩 중...</p>';

  try {
    const res  = await fetch(`/api/chart-data/${ticker}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (_lwChart) _lwChart.remove();
    container.innerHTML = '';

    const chart = LightweightCharts.createChart(container, {
      autoSize: true,
      layout:     { background: { color: '#050810' }, textColor: '#94a3b8' },
      grid:       { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
      crosshair:  { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.07)' },
      timeScale:  { borderColor: 'rgba(255,255,255,0.07)', timeVisible: true },
    });
    _lwChart = chart;

    chart.addHistogramSeries({
      priceScaleId: 'volume', priceFormat: { type: 'volume' },
      scaleMargins: { top: 0.85, bottom: 0 },
    }).setData(data.ohlcv.map(b => ({
      time: b.time, value: b.volume,
      color: b.close >= b.open ? 'rgba(52,211,153,0.15)' : 'rgba(244,63,94,0.15)',
    })));

    const candle = chart.addCandlestickSeries({
      upColor: '#10b981', downColor: '#f43f5e',
      borderUpColor: '#10b981', borderDownColor: '#f43f5e',
      wickUpColor: '#10b981', wickDownColor: '#f43f5e',
    });
    candle.setData(data.ohlcv);
    _candleSeries = candle;

    if (data.ma60 && data.ma60.length) {
      chart.addLineSeries({
        color: 'rgba(251,191,36,0.65)', lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false,
      }).setData(data.ma60);
    }

    if (data.ma20 && data.ma20.length) {
      chart.addLineSeries({
        color: 'rgba(99,179,237,0.8)', lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false,
      }).setData(data.ma20);
    }

    _allMarkers = data.markers || [];
    _applyMarkers();

  } catch (err) {
    container.innerHTML = `<p style="color:#f87171;padding:1rem;text-align:center">차트 로드 실패: ${err.message}</p>`;
  }
}

function _applyMarkers() {
  if (!_candleSeries) return;
  _candleSeries.setMarkers(_allMarkers.map(m => ({
    time:     m.time,
    position: m.type === 'buy' ? 'belowBar' : 'aboveBar',
    shape:    m.type === 'buy' ? 'arrowUp'  : 'arrowDown',
    color:    m.type === 'buy' ? '#34d399'  : '#f87171',
    text:     m.type === 'buy' ? 'B' : 'S',
    size: 1,
  })));
}

document.getElementById('modal-close').addEventListener('click', _closeModal);
document.getElementById('chart-modal').addEventListener('click', function (e) {
  if (e.target === this) _closeModal();
});
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') _closeModal();
});
