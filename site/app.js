/* Explore your major, next to economics (spec/front-end.yaml).
   #panel=compare|samejob|cause|rank|local renders one panel (one Canvas iframe each); no hash = the full
   explorer. Every number comes from the live bundle (../data/current.json). The chosen major is shared
   across frames by BroadcastChannel and sessionStorage (this tab only); each panel also has its own picker. Plain ES5. */
(function () {
  'use strict';

  var ECON = 'Economics', UNDECIDED = 'Undecided';
  var KEY = 'econ-major-dashboard:major';
  var PANELS = ['compare', 'lifetime', 'samejob', 'rank', 'local', 'cause'];   // figures first, the questions last (instructor 2026-10-26)
  var FILES = { compare: ['compare'], lifetime: ['lifetime'], samejob: ['same_occupation'], cause: ['same_occupation'],
                rank: ['rank'], local: ['local', 'codes'] };
  var TITLES = {
    compare: 'Your major and economics, side by side',
    lifetime: 'Earnings over a working life',
    samejob: 'In the same job, who earns more?',
    cause: 'Is it the major, or the students who choose it?',
    rank: 'Where the two majors rank',
    local: 'Here in South Florida'
  };
  var MEASURES = [
    { key: 'pay_early', name: 'Pay, early career', note: 'ages 22–27' },   // early before mid (instructor 2026-10-26)
    { key: 'pay_mid', name: 'Pay, mid-career', note: 'ages 35–45' },
    { key: 'unemployment', name: 'Unemployment', note: 'lower is better' },
    { key: 'underemployment', name: 'Underemployment', note: 'lower is better' }
  ];
  // Definitions copied from the specs (spec/rank-panel.yaml, spec/acs5-panels.yaml); data figures never live here
  var DEFS = {
    compare: 'Pay: median wages of full-time workers with a bachelor’s degree only, ages 22–27 (early career) ' +
             'and 35–45 (mid-career). Unemployment and underemployment: ages 22–27, bachelor’s degree or higher, ' +
             'not in school. Underemployed = working in a job that usually does not need a bachelor’s degree ' +
             '(our definition, from the O*NET survey of workers).',
    samejob: 'Same rules for all three groups: full-time workers, ages 25–54, wages. Economics majors and your ' +
             'major are weighted to the age mix of everyone in the job. Bachelor’s degree only unless the box ' +
             'above is checked.',
    rank: 'Pay: median wages, ages 35–45 (mid-career) and 22–27 (early career). Unemployment and ' +
          'underemployment: ages 22–27, bachelor’s degree or higher, not in school.',
    lifetime: 'Lifetime earnings: the median yearly earnings (wages and self-employment) of full-time, year-round ' +
              'workers (35+ hours a week, 50+ weeks a year) in eight age groups, 25–29 to 60–64, each times five, added up. ' +
              'Bachelor’s degree only unless the box above is checked.',
    local: 'Median wages of people who live in the area, ages 25–54, weighted to the age mix of all majors ' +
           'in the area.'
  };
  var NYFED = 'https://www.newyorkfed.org/research/college-labor-market';
  var JK = 'https://www.census.gov/library/publications/2011/acs/acs-14.html';   // Julian and Kominski (2011), instructor-confirmed
  var BLEEMER = 'https://doi.org/10.1257/app.20200447';   // Bleemer and Mehta (2022), AEJ: Applied; Zotero XTC9VCJ5; text approved 2026-10-26

  var state = { major: '', t: 0, jobList: 'mine', jobGrad: false, rankGrad: false, rankFull: true,
                localGrad: false, localFull: true, lifeGrad: false };
  var D = {}, majors = [], panels = [], full = false;

  // ---------- helpers ----------
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function money(v) { return '$' + (Math.round(v / 1000) * 1000).toLocaleString('en-US'); }
  function moneyMoe(v) { return '$' + (Math.max(100, Math.round(v / 100) * 100)).toLocaleString('en-US'); }   // margins can be a few hundred dollars
  function pct(v) { return v.toFixed(1) + '%'; }
  function fmt(kind, v) { return kind === 'pay' ? money(v) : pct(v); }
  function val(kind, c) { return kind === 'pay' ? c.median : c.rate; }
  function ordinal(n) {
    var s = ['th', 'st', 'nd', 'rd'], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
  function realPick() {
    return state.major && state.major !== ECON && state.major !== UNDECIDED && majors.indexOf(state.major) >= 0
      ? state.major : null;
  }
  // Hover (or tap) tooltip text for a chart element; lines joined by '\n' (instructor 2026-10-26: every chart interactive)
  function tip(lines) { return ' data-tip="' + esc(lines.filter(Boolean).join('\n')) + '"'; }
  function verdictWord(lab) { return lab === null || lab === undefined ? null : lab; }

  // Tick values for an axis from lo to hi (about n steps of 1, 2, 2.5, or 5 times a power of ten)
  function niceTicks(lo, hi, n) {
    if (!(hi > lo)) { hi = lo + 1; }
    var raw = (hi - lo) / n, p = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), steps = [1, 2, 2.5, 5, 10], step = p;
    for (var i = 0; i < steps.length; i++) { if (steps[i] * p >= raw) { step = steps[i] * p; break; } }
    var a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step, ticks = [];
    for (var t = a; t <= b + step / 1e6; t += step) { ticks.push(Math.round(t * 1e6) / 1e6); }
    return { lo: a, hi: b, ticks: ticks };
  }
  function tickLabel(kind, t) { return kind === 'pay' ? (t === 0 ? '$0' : '$' + t / 1000 + 'k') : t + '%'; }
  function tickHtml(kind, axis) {
    return axis.ticks.map(function (t, i) {
      var x = 100 * (t - axis.lo) / (axis.hi - axis.lo);
      var shift = i === 0 ? '0' : (i === axis.ticks.length - 1 ? '-100%' : '-50%');
      return '<span class="tick" style="left:' + x + '%;transform:translateX(' + shift + ')">' + tickLabel(kind, t) + '</span>';
    }).join('');
  }
  function gridHtml(axis) {
    return axis.ticks.slice(1).map(function (t) {
      return '<span class="grid" style="left:' + 100 * (t - axis.lo) / (axis.hi - axis.lo) + '%"></span>';
    }).join('');
  }
  // "better on 2 measures, about the same on 1, and worse on 1"
  function countLine(c, unit, words) {
    var parts = [];
    if (c.better) { parts.push(words.better + ' ' + plural(c.better, unit)); }
    if (c['about the same']) { parts.push(words.same + ' ' + plural(c['about the same'], unit)); }
    if (c.worse) { parts.push(words.worse + ' ' + plural(c.worse, unit)); }
    if (parts.length < 2) { return parts.join(''); }
    return parts.slice(0, -1).join(', ') + ', and ' + parts[parts.length - 1];
  }
  function yearsText(s) {        // "ACS 2020-24 5-year" -> "2020–24 (five-year file)"
    return s.replace(/^ACS\s+/, '').replace(/(\d{4})-(\d{2})/, '$1–$2')
      .replace(/\s+1-year$/, ' (one-year file)').replace(/\s+5-year$/, ' (five-year file)');
  }
  function dollarYear() { var m = /(\d{4}) dollars/.exec(D.manifest.dollars || ''); return m ? m[1] : ''; }
  function table(id, caption, head, rows) {
    return '<details class="table" id="' + id + '"><summary>Show the data table</summary><div class="scroll"><table>' +
      '<caption>' + caption + '</caption><thead><tr>' + head.map(function (h, i) {
        return '<th scope="col"' + (i ? ' class="num"' : '') + '>' + h + '</th>';
      }).join('') + '</tr></thead><tbody>' + rows.map(function (r) {
        return '<tr>' + r.map(function (c, i) {
          return i ? '<td class="num">' + c + '</td>' : '<th scope="row">' + c + '</th>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table></div></details>';
  }
  function withMoe(kind, c, tag) {
    if (!c || c.hidden) { return 'not enough data'; }
    return '<span data-v="' + tag + '">' + fmt(kind, val(kind, c)) + '</span> (± ' + (kind === 'pay' ? moneyMoe(c.moe) : pct(c.moe)) + ')';
  }

  // ---------- panel 1: side by side ----------
  function renderCompare() {
    var pick = realPick(), otherName = pick ? pick + ' majors' : 'all majors';
    var counts = { better: 0, 'about the same': 0, worse: 0 }, na = 0, figs = [], trows = [], mid = null;
    MEASURES.forEach(function (ms) {
      var m = D.compare.measures[ms.key], kind = m.kind;
      var rows = [{ cls: 'econ', name: ECON, cell: m.economics }];
      if (pick) { rows.push({ cls: 'major', name: pick, cell: m.by_major[pick].major }); }
      rows.push({ cls: 'all', name: 'All majors', cell: m.all });
      var lab = verdictWord((pick ? m.by_major[pick].econ_vs_major : m.econ_vs_all).label);
      if (lab) { counts[lab] += 1; } else { na += 1; }
      if (ms.key === 'pay_mid') { mid = { lab: lab, e: m.economics, o: pick ? m.by_major[pick].major : m.all }; }
      // one axis per measure for every major, so bars keep their scale when the major changes
      var mx = Math.max(val(kind, m.all), val(kind, m.economics));
      Object.keys(m.by_major).forEach(function (k) {
        var c = m.by_major[k].major;
        if (!c.hidden) { mx = Math.max(mx, val(kind, c)); }
      });
      var axis = niceTicks(0, mx, 4);
      var bars = rows.map(function (r) {
        var cell;
        if (r.cell.hidden) {
          cell = '<span class="bar-na">not enough data</span>';
        } else {
          var w = 100 * val(kind, r.cell) / axis.hi, inside = w > 60;
          var v = '<span class="bar-val ' + r.cls + (inside ? ' inside' : '') + '" data-v="' + ms.key + '|' + r.cls + '">' +
                  fmt(kind, val(kind, r.cell)) + '</span>';
          cell = '<span class="bar ' + r.cls + '" style="width:' + w.toFixed(2) + '%;height:20px">' + (inside ? v : '') + '</span>' +
                 (inside ? '' : v);
        }
        var t = r.cell.hidden ? [r.name + ': not enough data'] :
          [r.name + ': ' + fmt(kind, val(kind, r.cell)), 'Margin of error: ± ' + (kind === 'pay' ? moneyMoe(r.cell.moe) : pct(r.cell.moe)),
           ms.name + ', ' + ms.note];
        return '<div class="brow"' + tip(t) + '><span class="bar-name ' + r.cls + '">' + esc(r.name) + '</span><span class="bcell">' +
               gridHtml(axis) + cell + '</span></div>';
      }).join('');
      var verdict = lab ? 'Economics vs ' + esc(otherName) + ': ' + lab : 'Not enough data to compare';
      figs.push('<figure role="group" aria-label="' + esc(ms.name + '. ' + verdict) + '"><figcaption><span class="cap-top"><b>' +
                ms.name + '</b><span>' + ms.note + '</span></span><span class="verdict' + (lab === 'better' ? ' better' : '') +
                '">' + verdict + '</span></figcaption><div class="bars" aria-hidden="true">' + bars +
                '<div class="brow"><span></span><span class="ticks">' + tickHtml(kind, axis) + '</span></div></div></figure>');
      trows.push([ms.name + ' (' + ms.note + ')', withMoe(kind, m.economics, ms.key + '|econ')]
        .concat(pick ? [withMoe(kind, m.by_major[pick].major, ms.key + '|major')] : [])
        .concat([withMoe(kind, m.all, ms.key + '|all'), lab || 'not enough data']));
    });

    var line = countLine(counts, 'measure', { better: 'better on', same: 'about the same on', worse: 'worse on' });
    var naLine = na ? ' There is not enough data on ' + plural(na, 'measure') + '.' : '';
    var head, sub;
    if (pick) {
      head = 'Compared with ' + esc(pick) + ', economics does ' + line + '.' + naLine;
    } else if (state.major === ECON) {
      head = 'You picked economics. Compared with all majors, it does ' + line + '.' + naLine;
    } else {
      head = state.major === UNDECIDED ? 'Undecided? Start here: economics compared with all majors.'
        : 'Pick a major to compare it with economics.';
    }
    sub = midLine(mid, otherName);
    if (!pick && state.major !== ECON) { sub = 'Until then, the charts compare economics with all majors: economics does ' + line + '. ' + sub; }
    var y = yearsText(D.manifest.years.rank);
    return '<div class="headline"><strong>' + head + '</strong><span>' + sub + '</span></div>' +
      '<div class="metrics">' + figs.join('') + '</div>' +
      '<p class="notes">“About the same” means the data cannot tell the two apart: the gap is inside the margin of error (90%).</p>' +
      table('table-compare', 'Economics, ' + esc(pick || 'all majors') + ', and all majors, with 90% margins of error',
            ['Measure', 'Economics'].concat(pick ? [esc(pick)] : []).concat(['All majors', 'Economics vs ' + esc(otherName)]), trows) +
      '<div class="notes"><p>' + DEFS.compare + '</p><p>Data: U.S. Census Bureau, American Community Survey ' + y +
      '. Our calculations, following the <a href="' + NYFED + '">New York Fed’s</a> method; majors are our grouping, close to its 73. Pay in ' + dollarYear() + ' dollars.</p></div>';
  }

  function midLine(mid, otherName) {
    if (!mid.lab) { return 'There are too few ' + esc(otherName) + ' in the data to compare mid-career pay.'; }
    var g = Math.round((mid.e.median - mid.o.median) / 1000) * 1000;
    if (mid.lab === 'about the same' || g === 0) {
      return 'At mid-career, the pay gap between economics majors and ' + esc(otherName) + ' (' + money(Math.abs(g)) +
             ' a year) is inside the margin of error.';
    }
    return g > 0 ? 'At mid-career, economics majors earn ' + money(g) + ' a year more than ' + esc(otherName) + '.'
      : 'At mid-career, ' + esc(otherName) + ' earn ' + money(-g) + ' a year more than economics majors.';
  }

  // ---------- panel 2: same job ----------
  function jobList(grad) {
    var pick = realPick(), v = D.same_occupation['grad=' + (grad ? 1 : 0)][pick || ECON];
    var mine = pick && state.jobList === 'mine';
    return { pick: pick, mine: mine, t: pick ? v[mine ? 'major_top' : 'economics_top'] : v.major_top,
             dk: pick ? 'econ_vs_major' : 'econ_vs_all' };
  }
  // "more in 5 of these 10 jobs, about the same in 2, and less in 1"; '' if every row is hidden
  function jobCounts(c, n) {
    var parts = [];
    if (c.better) { parts.push('more in ' + c.better); }
    if (c['about the same']) { parts.push('about the same in ' + c['about the same']); }
    if (c.worse) { parts.push('less in ' + c.worse); }
    if (!parts.length) { return ''; }
    parts[0] += ' of these ' + n + ' jobs';
    return parts.length < 2 ? parts[0] : parts.slice(0, -1).join(', ') + ', and ' + parts[parts.length - 1];
  }
  function jobHeadline(L) {
    var line = jobCounts(L.t.headline, L.t.rows.length);
    if (!line) { return 'In these ' + L.t.rows.length + ' jobs, there are too few people to compare.'; }
    return (L.pick ? 'Compared with ' + esc(L.pick) + ' majors in the same job' : 'Compared with everyone in the same job') +
      ', economics majors earn ' + line + '.';
  }
  function renderSamejob() {
    var L = jobList(state.jobGrad), pick = L.pick, rows = L.t.rows;
    var shown = rows.filter(function (r) { return r[L.dk].label; });
    var folded = rows.filter(function (r) { return !r[L.dk].label; });
    var h = '';
    if (pick) {
      h += '<div class="toggle" role="group" aria-label="Which jobs to list">' +
        '<button type="button" id="job-mine" data-list="mine" aria-pressed="' + !!L.mine + '">Top jobs for ' + esc(pick) + ' majors</button>' +
        '<button type="button" id="job-econ" data-list="econ" aria-pressed="' + !L.mine + '">Top jobs for economics majors</button></div>';
    }
    h += '<div class="controls"><label class="check"><input type="checkbox" id="job-grad" data-act="jobGrad"' +
      (state.jobGrad ? ' checked' : '') + '> Include people with graduate degrees</label></div>';
    h += '<div class="headline"><strong>' + jobHeadline(L) + '</strong><span>Jobs where economics majors earn less stay in the list.' +
      (pick ? '' : ' Pick a major to compare it with economics in each job.') + '</span></div>';
    h += '<div class="legend" aria-hidden="true"><span><i class="dot-key" style="background:var(--navy)"></i>Economics majors</span>' +
      (pick ? '<span><i class="dot-key" style="background:var(--teal)"></i>' + esc(pick) + ' majors</span>' : '') +
      '<span><i class="dash-key"></i>Everyone in the job</span></div>';
    var title = L.mine ? 'Top jobs for ' + esc(pick) + ' majors' : 'Top jobs for economics majors';
    h += '<div class="jobs" role="list" aria-label="' + title + '">';
    if (shown.length) {
      var lo = Infinity, hi = -Infinity;
      shown.forEach(function (r) {
        [r.economics, pick ? r.major : null].forEach(function (c) {
          if (c && !c.hidden) { lo = Math.min(lo, c.median - c.moe); hi = Math.max(hi, c.median + c.moe); }
        });
        lo = Math.min(lo, r.all.median); hi = Math.max(hi, r.all.median);
      });
      var axis = niceTicks(Math.max(0, lo), hi, 4);
      var x = function (v) { return Math.max(0, Math.min(100, 100 * (v - axis.lo) / (axis.hi - axis.lo))); };
      shown.forEach(function (r) {
        var lab = r[L.dk].label;
        var dots = function (c, cls) {
          if (!c || c.hidden) { return ''; }
          var a = x(c.median - c.moe), b = x(c.median + c.moe);
          return '<div class="dot-row"><span class="band ' + cls + '" style="left:' + a + '%;width:' + (b - a) + '%"></span>' +
                 '<span class="dot ' + cls + '" style="left:' + x(c.median) + '%"></span></div>';
        };
        h += '<div class="job" role="listitem"><div><div class="job-name">' + esc(r.label) + '</div><div class="job-vals">' +
          '<b class="econ">Economics <span data-v="job|' + r.occp + '|econ">' + money(r.economics.median) + '</span></b>' +
          (pick ? ' · <b class="major">' + esc(pick) + ' <span data-v="job|' + r.occp + '|major">' + money(r.major.median) + '</span></b>' : '') +
          ' · Everyone <span data-v="job|' + r.occp + '|all">' + money(r.all.median) + '</span> · economics: ' + lab + '</div></div>' +
          '<div class="dots" aria-hidden="true"' + tip([r.label, 'Economics majors: ' + money(r.economics.median) + ' (± ' + moneyMoe(r.economics.moe) + ')',
            pick ? (r.major.hidden ? pick + ' majors: not enough data' : pick + ' majors: ' + money(r.major.median) + ' (± ' + moneyMoe(r.major.moe) + ')') : '',
            'Everyone in the job: ' + money(r.all.median)]) + '>' + gridHtml(axis) + '<span class="all-line" style="left:' + x(r.all.median) + '%"></span>' +
          dots(r.economics, 'econ') + (pick ? dots(r.major, 'major') : '') + '</div></div>';
      });
      h += '<div class="axis-row" aria-hidden="true"><div></div><div><div class="axis">' + tickHtml('pay', axis) + '</div>' +
        '<div class="notes" style="text-align:center;margin-top:4px">Median pay. Dot = median; shaded band = margin of error.</div></div></div>';
    }
    if (folded.length) {
      var econH = folded.every(function (r) { return r.economics.hidden; });
      var majH = pick && folded.every(function (r) { return r.major && r.major.hidden && !r.economics.hidden; });
      var who = majH ? esc(pick) + ' majors' : (econH || !pick ? 'economics majors' : 'economics majors or ' + esc(pick) + ' majors');
      h += '<div class="fold" role="listitem">In ' + (folded.length === rows.length ? 'all ' : '') + folded.length + ' of these ' +
        rows.length + ' jobs, too few ' + who + ' work there to compare: ' +
        folded.map(function (r) { return esc(r.label); }).join('; ') + '.</div>';
    }
    h += '</div>';
    var share = pick ? esc(pick) + ' majors' : 'economics majors';
    h += table('table-samejob', title + ': median pay with 90% margins of error',
      ['Job', 'Share of ' + share + ' in it', 'Economics'].concat(pick ? [esc(pick)] : []).concat(['Everyone in the job', 'Economics vs ' + (pick ? esc(pick) : 'everyone')]),
      rows.map(function (r) {
        return [esc(r.label), (100 * r.major_share.share).toFixed(1) + '%', withMoe('pay', r.economics, 'job|' + r.occp + '|econ')]
          .concat(pick ? [withMoe('pay', r.major, 'job|' + r.occp + '|major')] : [])
          .concat([withMoe('pay', r.all, 'job|' + r.occp + '|all'), r[L.dk].label || 'not enough data']);
      }));
    h += '<div class="notes"><p>This panel compares people in the same job, under the same rules. That removes one reason for a gap. ' +
      'People in one job still differ in experience, employer, and hours, so the panel does not show that the major causes the gap.</p>' +
      '<p>' + DEFS.samejob + '</p><p>Data: U.S. Census Bureau, American Community Survey ' + yearsText(D.manifest.years.other) +
      '. Our calculations, adapted from Bartsch (2026), who used broader job groups and averages. Pay in ' + dollarYear() + ' dollars.</p></div>';
    return h;
  }

  // ---------- panel 3: cause or selection ----------
  function renderCause() {
    var L = jobList(false), c = L.t.headline;
    var n = L.t.rows.length, line = jobCounts(c, n);
    var whose = 'the ' + n + ' most common jobs for ' + (L.pick ? esc(L.pick) : 'economics') + ' majors';
    var than = L.pick ? esc(L.pick) + ' majors' : 'everyone';
    var p2 = line ? 'Look at ' + whose + '. Compared with ' + than + ' in the same job, economics majors earn ' + line +
      (L.t.hidden_rows ? '; the rest have too few people to compare' : '') + '. ' +
      (c.better ? 'So a gap remains even inside the same job.' : 'Inside these jobs, the data do not show a gap in favor of economics.')
      : 'In ' + whose + ', there are too few people to compare.';
    function obj(id, q, a) {
      return '<details class="objection" id="' + id + '"><summary>' + q + '</summary><p>' + a + '</p></details>';
    }
    return '<p class="lede">A skeptic says economics majors would earn more with any degree. Open each objection to see the answer.</p>' +
      obj('obj-1', '“It is only a few very high earners.”',
          'The pay numbers on this page are medians: the person in the middle. A few very high earners cannot move a median.') +
      obj('obj-2', '“Economics majors just pick high-paying jobs.”', 'Partly. The same-job panel compares people in the same job. ' + p2) +
      obj('obj-3', '“More able students, or students from top schools, choose economics.”',
          'The census does not record ability or which college a person attended, so it cannot test this. A natural experiment can. ' +
          'At the University of California, Santa Cruz, students needed a 2.8 grade average in the first two economics courses to ' +
          'declare the major; students below it generally could not. Students just above and just below the cutoff were almost the same. ' +
          '<a href="' + BLEEMER + '">Bleemer and Mehta (2022)</a> found that students who just made the cutoff and majored in economics ' +
          'earned about $22,000 a year more at ages 23 to 28 than they would have in their second-choice majors: over $59,000 instead ' +
          'of about $37,000 (2018 dollars). About half of the gain came from jobs in higher-paying industries, such as finance and ' +
          'accounting. The result holds for those students at that university. It is evidence, not a promise for every student.');
  }

  // ---------- panel: lifetime earnings (spec/lifetime-panel.yaml) ----------
  function millions(v) { return '$' + (v / 1e6).toFixed(2) + ' million'; }
  function lifeMoe(c) { return '± $' + Math.max(1000, Math.round(c.moe / 1000) * 1000).toLocaleString('en-US'); }
  function ageChart(groups) {
    // groups: [{cls, name, cell}] with eight bands each; one line per shown group
    var shown = groups.filter(function (g) { return !g.cell.hidden; }), mx = 0;
    shown.forEach(function (g) { g.cell.bands.forEach(function (b) { mx = Math.max(mx, b.median); }); });
    var axis = niceTicks(0, mx, 4), W = 360, H = 190, L = 44, R = 8, T = 10, B = 26;
    var x = function (i) { return L + (W - L - R) * (i + 0.5) / 8; };
    var y = function (v) { return T + (H - T - B) * (1 - (v - axis.lo) / (axis.hi - axis.lo)); };
    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="agechart" aria-hidden="true" focusable="false">';
    axis.ticks.forEach(function (t) {
      svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(t) + '" y2="' + y(t) + '" class="ag-grid"/>' +
             '<text x="' + (L - 6) + '" y="' + (y(t) + 4) + '" text-anchor="end" class="ag-tick">' + tickLabel('pay', t) + '</text>';
    });
    (shown[0] ? shown[0].cell.bands : []).forEach(function (b, i) {
      svg += '<text x="' + x(i) + '" y="' + (H - 8) + '" text-anchor="middle" class="ag-tick">' + b.ages.replace('-', '–') + '</text>';
    });
    shown.forEach(function (g) {
      var pts = g.cell.bands.map(function (b, i) { return x(i).toFixed(1) + ',' + y(b.median).toFixed(1); });
      svg += '<polyline points="' + pts.join(' ') + '" class="ag-line ' + g.cls + '"/>' +
             pts.map(function (pt) { var q = pt.split(','); return '<circle cx="' + q[0] + '" cy="' + q[1] + '" r="3" class="ag-dot ' + g.cls + '"/>'; }).join('');
    });
    (shown[0] ? shown[0].cell.bands : []).forEach(function (b, i) {
      var w = (W - L - R) / 8;
      svg += '<rect x="' + (x(i) - w / 2) + '" y="' + T + '" width="' + w + '" height="' + (H - T - B) + '" class="ag-hit"' +
        tip(['Ages ' + b.ages.replace('-', '–')].concat(shown.map(function (g) { return g.name + ': ' + money(g.cell.bands[i].median) + ' a year'; }))) + '/>';
    });
    var legend = '<div class="legend" aria-hidden="true">' + shown.map(function (g) {
      var col = { econ: 'var(--navy)', major: 'var(--teal)', all: 'var(--gray)' }[g.cls];
      return '<span><i class="dot-key" style="background:' + col + '"></i>' + esc(g.name) + '</span>';
    }).join('') + '</div>';
    return '<figure role="group" aria-label="Median yearly earnings by age group (the data table has every value)">' +
      '<figcaption><span class="cap-top"><b>Median yearly earnings by age</b><span>full-time, year-round</span></span></figcaption>' +
      svg + '</svg>' + legend + '</figure>';
  }
  function renderLifetime() {
    var pick = realPick(), k = 'grad=' + (state.lifeGrad ? 1 : 0), L = D.lifetime[k];
    var groups = [{ cls: 'econ', tag: 'econ', name: ECON, cell: L.economics }];
    if (pick) { groups.push({ cls: 'major', tag: 'major', name: pick, cell: L.by_major[pick].major }); }
    groups.push({ cls: 'all', tag: 'all', name: 'All bachelor’s', cell: L.all_bachelors });
    var mx = 0;
    [L.economics, L.all_bachelors].concat(Object.keys(L.by_major).map(function (m) { return L.by_major[m].major; }))
      .forEach(function (c) { if (!c.hidden) { mx = Math.max(mx, c.total); } });
    var axis = niceTicks(0, mx, 4);
    var bars = groups.map(function (g) {
      var cell;
      if (g.cell.hidden) {
        cell = '<span class="bar-na">not enough data</span>';
      } else {
        var w = 100 * g.cell.total / axis.hi, inside = w > 60;
        var v = '<span class="bar-val ' + g.cls + (inside ? ' inside' : '') + '" data-v="life|' + g.tag + '">' + millions(g.cell.total) + '</span>';
        cell = '<span class="bar ' + g.cls + '" style="width:' + w.toFixed(2) + '%;height:20px">' + (inside ? v : '') + '</span>' + (inside ? '' : v);
      }
      var t = g.cell.hidden ? [g.name + ': not enough data'] : [g.name + ': ' + millions(g.cell.total), 'Margin of error: ' + lifeMoe(g.cell),
        'Ages 25–64, added up from eight age groups'];
      return '<div class="brow"' + tip(t) + '><span class="bar-name ' + g.cls + '">' + esc(g.name) + '</span><span class="bcell">' + gridHtml(axis) + cell + '</span></div>';
    }).join('');
    var mticks = '<span class="ticks">' + axis.ticks.map(function (t, i) {
      var shift = i === 0 ? '0' : (i === axis.ticks.length - 1 ? '-100%' : '-50%');
      return '<span class="tick" style="left:' + 100 * (t - axis.lo) / (axis.hi - axis.lo) + '%;transform:translateX(' + shift + ')">' +
        (t === 0 ? '$0' : '$' + t / 1e6 + 'M') + '</span>';
    }).join('') + '</span>';
    var vs = pick ? L.by_major[pick].econ_vs_major : L.econ_vs_all, other = pick ? pick + ' majors' : 'all bachelor’s holders';
    var head;
    if (L.economics.hidden) {
      head = 'There is not enough data on economics majors for this setting.';
    } else if (pick && L.by_major[pick].major.hidden) {
      head = 'There are too few ' + esc(pick) + ' majors in the data to add up a working life.';
    } else {
      head = 'Over a working life, economics majors earn about ' + millions(L.economics.total) + '; ' + esc(other) + ', about ' +
        millions((pick ? L.by_major[pick].major : L.all_bachelors).total) + '.';
    }
    var verdict = vs.label ? 'Economics vs ' + esc(other) + ': ' + vs.label : 'Not enough data to compare';
    var sub = !vs.label ? '' : vs.label === 'about the same' ? 'The data cannot tell the two apart: the gap is inside the margin of error.'
      : 'That is a gap of about ' + millions(Math.abs(vs.d)) + ' over a working life.';
    var trows = groups.map(function (g) {
      return [esc(g.name), g.cell.hidden ? 'not enough data' : '<span data-v="life|' + g.tag + '">' + millions(g.cell.total) + '</span> (' + lifeMoe(g.cell) + ')']
        .concat(g.cell.hidden ? ['', '', '', '', '', '', '', ''] : g.cell.bands.map(function (b) { return money(b.median); }));
    });
    var bandHead = (L.economics.bands.length ? L.economics.bands : L.all_bachelors.bands).map(function (b) { return 'Ages ' + b.ages.replace('-', '–'); });
    return '<div class="controls" role="group" aria-label="Who is counted"><label class="check"><input type="checkbox" id="life-grad" data-act="lifeGrad"' +
      (state.lifeGrad ? ' checked' : '') + '> Include people with graduate degrees</label></div>' +
      '<div class="headline"><strong>' + head + '</strong><span>' + sub + '</span></div>' +
      '<div class="metrics"><figure role="group" aria-label="' + esc('Lifetime earnings. ' + verdict) + '"><figcaption><span class="cap-top"><b>Lifetime earnings</b>' +
      '<span>ages 25–64</span></span><span class="verdict' + (vs.label === 'better' ? ' better' : '') + '">' + verdict + '</span></figcaption>' +
      '<div class="bars" aria-hidden="true">' + bars + '<div class="brow"><span></span>' + mticks + '</div></div></figure>' +
      ageChart(groups) + '</div>' +
      table('table-lifetime', 'Lifetime earnings with 90% margins of error, and the median yearly earnings in each age group',
            ['Group', 'Lifetime'].concat(bandHead), trows) +
      '<div class="notes"><p>' + DEFS.lifetime + '</p><p>This is a snapshot of today’s workers at each age, added up. It is not one ' +
      'person’s future earnings, and it is not adjusted for interest, future inflation, or taxes. A gap does not prove that the ' +
      'major causes it: see the questions at the end.</p><p>Data: U.S. Census Bureau, American Community Survey ' +
      yearsText(D.manifest.years.other) + '. Our calculations, following the Census Bureau’s method (<a href="' + JK +
      '">Julian and Kominski 2011</a>). Pay in ' + dollarYear() + ' dollars.</p></div>';
  }

  // ---------- panel 4: rank ----------
  function renderRank() {
    var pick = realPick(), cards = [], trows = [];
    var setting = '|grad=' + (state.rankGrad ? 1 : 0) + '|fulltime=' + (state.rankFull ? 1 : 0);
    MEASURES.forEach(function (ms) {
      var key = ms.key.indexOf('pay') === 0 ? ms.key + setting : ms.key;
      var rows = D.rank.measures[key], kind = ms.key.indexOf('pay') === 0 ? 'pay' : 'rate';
      var find = function (m) { for (var i = 0; i < rows.length; i++) { if (rows[i].major === m) { return rows[i]; } } return null; };
      var rk = function (r) {
        if (!r || r.hidden) { return 'not enough data'; }
        var tied = rows.filter(function (x) { return x.rank === r.rank; }).length > 1;
        return (tied ? 'tied ' : '') + '<span data-v="rank|' + ms.key + '|' + (r.major === ECON ? 'econ' : 'major') + '">' +
          ordinal(r.rank) + '</span> of ' + rows.length;
      };
      var e = find(ECON), p = pick ? find(pick) : null;
      cards.push('<div class="card"><span class="what">' + ms.name + ' · 1 = ' + (kind === 'pay' ? 'highest pay' : 'lowest rate') + '</span>' +
        '<span class="big">Economics: ' + rk(e) + '</span>' +
        (pick ? '<span class="line major"><b>' + esc(pick) + ': ' + rk(p) + '</b></span>' : '') +
        (ms.key === 'unemployment' ? '<span class="small">Most majors’ unemployment rates are too close together to rank with ' +
          'confidence, so treat a rank on this measure as rough.</span>' : '') + '</div>');
      var v = function (r) { return r && !r.hidden ? fmt(kind, r.estimate) : 'not enough data'; };
      trows.push([ms.name, rk(e), v(e)].concat(pick ? [rk(p), v(p)] : []));
    });
    return '<div class="controls" role="group" aria-label="How pay is measured">' +
      '<label class="check"><input type="checkbox" id="rank-grad" data-act="rankGrad"' + (state.rankGrad ? ' checked' : '') +
      '> Include people with graduate degrees (pay)</label>' +
      '<label class="check"><input type="checkbox" id="rank-full" data-act="rankFull"' + (state.rankFull ? ' checked' : '') +
      '> Full-time workers only (pay)</label></div>' +
      '<div class="cards">' + cards.join('') + '</div>' +
      table('table-rank', 'Ranks among all majors', ['Measure', 'Economics rank', 'Economics'].concat(pick ? [esc(pick) + ' rank', esc(pick)] : []), trows) +
      '<div class="notes"><p>' + DEFS.rank + ' Majors with too few people in the data show “not enough data”.</p>' +
      '<p>Data: U.S. Census Bureau, American Community Survey ' + yearsText(D.manifest.years.rank) +
      '. Our calculations, following the <a href="' + NYFED + '">New York Fed’s</a> method; majors are our grouping, close to its 73.</p></div>';
  }

  // ---------- panel 5: local ----------
  function renderLocal() {
    var pick = realPick(), k = 'grad=' + (state.localGrad ? 1 : 0) + '|fulltime=' + (state.localFull ? 1 : 0), cards = [];
    [['florida', 'Living in Florida'], ['south_florida', 'Living in South Florida']].forEach(function (pair) {
      var a = D.local[k][pair[0]], tag = 'local|' + pair[0];
      var line = function (cls, name, c, t) {
        return '<span class="line"><b class="' + cls + '">' + esc(name) + '</b> ' +
          (c && !c.hidden ? '<span data-v="' + tag + '|' + t + '">' + money(c.median) + '</span>' : 'not enough data') + '</span>';
      };
      var lab = verdictWord((pick ? a.by_major[pick].econ_vs_major : a.econ_vs_all).label);
      cards.push('<div class="card"><span class="what">' + pair[1] + '</span>' + line('econ', ECON, a.economics, 'econ') +
        (pick ? line('major', pick, a.by_major[pick].major, 'major') : '') + line('all', 'All majors', a.all, 'all') +
        '<span class="small">' + (lab ? 'Economics vs ' + esc(pick || 'all majors') + ': ' + lab : 'Not enough data to compare') + '</span></div>');
    });
    return '<div class="controls" role="group" aria-label="Who is counted">' +
      '<label class="check"><input type="checkbox" id="local-grad" data-act="localGrad"' + (state.localGrad ? ' checked' : '') +
      '> Include people with graduate degrees</label>' +
      '<label class="check"><input type="checkbox" id="local-full" data-act="localFull"' + (state.localFull ? ' checked' : '') +
      '> Full-time workers only</label></div>' +
      '<div class="cards">' + cards.join('') + '</div>' +
      '<div class="notes"><p>' + DEFS.local + '</p><p>South Florida = Miami-Dade, Broward, and Palm Beach counties: the ' +
      D.codes.south_florida_pumas.length + ' Census areas (PUMAs) that lie fully inside them. One area that joins Monroe County ' +
      'with part of Miami-Dade is left out.</p><p>Data: U.S. Census Bureau, American Community Survey ' +
      yearsText(D.manifest.years.other) + '. Our calculations. Pay in ' + dollarYear() + ' dollars.</p></div>';
  }

  var RENDER = { compare: renderCompare, lifetime: renderLifetime, samejob: renderSamejob, cause: renderCause, rank: renderRank, local: renderLocal };

  // ---------- page shell ----------
  function picker(id) {
    var opts = '<option value="">Choose a major</option><option value="' + UNDECIDED + '">' + UNDECIDED + '</option>' +
      '<option value="' + ECON + '">' + ECON + '</option>' + majors.map(function (m) {
        return '<option value="' + esc(m) + '">' + esc(m) + '</option>';
      }).join('');
    return '<div class="picker"><label for="pick-' + id + '">I plan to major in</label><select id="pick-' + id +
      '" class="major-pick">' + opts + '</select><span class="hint">All ' + (majors.length + 1) +
      ' majors. The choice carries to every panel.</span></div>';
  }
  // ---------- stale-data note (spec/scheduler.yaml stale_note_11_4) ----------
  // lc: 'missing' (404: the scheduler is not armed yet), 'unreadable', or the parsed data/last-checked.json
  var STALE_DAYS = 45;
  function longDate(d) {
    var m = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
             'November', 'December'];
    return m[d.getUTCMonth()] + ' ' + d.getUTCDate() + ', ' + d.getUTCFullYear();
  }
  function staleNote(lc, now) {
    if (lc === 'missing') { return { note: null, footer: null }; }
    var t = lc && typeof lc === 'object' && typeof lc.last_success === 'string' ? new Date(lc.last_success) : null;
    if (!t || isNaN(t.getTime())) {
      return { note: 'This page could not confirm when it last checked for new Census data.', footer: null };
    }
    var days = (now.getTime() - t.getTime()) / 86400000;
    return { note: days > STALE_DAYS ? 'This page last checked for new Census data on ' + longDate(t) +
               '. Newer numbers may exist.' : null, footer: longDate(t) };
  }
  function staleBanner() {
    var s = staleNote(D.lastChecked, new Date());
    return s.note ? '<p class="stale" role="note">' + esc(s.note) + '</p>' : '';
  }
  window.EMD = { staleNote: staleNote };                          // for tests/site/stale.html

  function footer() {
    var s = staleNote(D.lastChecked, new Date());
    var lc = s.footer ? ' Last checked for new data: ' + esc(s.footer) + '.' : '';
    return '<div class="footer"><p><strong>Updates itself.</strong> Data: U.S. Census Bureau, American Community Survey ' +
      yearsText(D.manifest.years.rank) + ' and ' + yearsText(D.manifest.years.other) + '.' + lc + '</p>' +
      '<p>Our calculations, following the methods of the New York Fed and Holian and Chiu (2026), and adapted from Bartsch (2026). ' +
      'Majors are our own grouping of Census degree codes into the New York Fed’s 73 majors; job names are the Census Bureau’s.</p>' +
      '<p class="links"><a href="' + NYFED + '">New York Fed: The Labor Market for Recent College Graduates</a></p></div>';
  }
  function shell() {
    var h = '';
    if (full) {
      document.body.className = 'full';
      h += '<div class="intro"><span class="rule"></span><span class="kicker">Choosing a major</span>' +
        '<h1>Explore your major, next to economics</h1><p class="lede">Pick the major you plan to study. The panels compare it ' +
        'with economics and with all majors: pay, unemployment, the jobs graduates hold, and why the gaps exist.</p>' +
        picker('top') + '</div>';
    }
    panels.forEach(function (p) {
      h += '<section class="panel" id="panel-' + p + '" aria-labelledby="h-' + p + '"><h2 id="h-' + p + '">' + TITLES[p] + '</h2>' +
        (full ? '' : picker(p)) + staleBanner() + '<div class="panel-body" id="body-' + p + '"></div>' +
        (full ? '' : (p === PANELS[PANELS.length - 1] ? footer() : '') +
          '<p class="open-full"><a href="index.html" target="_blank" rel="noopener">Open the full explorer</a></p>') + '</section>';
    });
    if (full) { h += footer(); }
    document.getElementById('app').innerHTML = h;
  }

  // Re-render the panel bodies; keep focus and open <details> by id (keyboard users stay in place)
  function render() {
    var active = document.activeElement && document.activeElement.id;
    var open = [].slice.call(document.querySelectorAll('details[open]')).map(function (d) { return d.id; });
    panels.forEach(function (p) { document.getElementById('body-' + p).innerHTML = RENDER[p](); });
    open.forEach(function (id) { var d = document.getElementById(id); if (d) { d.open = true; } });
    [].slice.call(document.querySelectorAll('.major-pick')).forEach(function (s) { s.value = state.major; });
    if (active) { var el = document.getElementById(active); if (el && el !== document.activeElement) { el.focus(); } }
  }

  // ---------- shared major ----------
  // Each choice carries the time it was made; a frame keeps the newest, so a late reply never undoes a pick
  var bc = null;
  function setMajor(m, from, t) {
    if (m !== '' && m !== ECON && m !== UNDECIDED && majors.indexOf(m) < 0) { return; }
    t = from === 'user' ? Math.max(Date.now(), state.t + 1) : Number(t) || 0;
    if (t <= state.t) { return; }
    var changed = m !== state.major;
    state.major = m; state.t = t;
    if (from !== 'storage') {
      try { sessionStorage.setItem(KEY, JSON.stringify({ major: m, t: t })); } catch (e) { /* storage blocked: pickers still work */ }
    }
    if (from === 'user' && bc) { bc.postMessage({ type: 'major', major: m, t: t }); }
    if (changed) { render(); }
  }
  function stored(s) {
    try { var o = JSON.parse(s); return o && typeof o.major === 'string' ? o : null; } catch (e) { return null; }
  }
  function listen() {
    // One channel per browser tab (E45): a BroadcastChannel reaches every tab, so a dashboard open in another tab
    // would answer this tab's 'hello' with its own pick. The tab id lives in sessionStorage, which the frames of one
    // tab share; if storage is blocked, all tabs share one channel (the old behavior).
    var tab = '';
    try {
      tab = sessionStorage.getItem(KEY + ':tab') || '';
      if (!tab) { tab = String(Date.now()) + Math.random().toString(36).slice(2, 8); sessionStorage.setItem(KEY + ':tab', tab); }
    } catch (e) { tab = ''; }
    try { bc = new BroadcastChannel('econ-major-dashboard' + (tab ? ':' + tab : '')); } catch (e) { bc = null; }
    if (bc) {
      bc.onmessage = function (e) {
        var d = e.data || {};
        if (d.type === 'major') { setMajor(String(d.major), 'remote', d.t); }
        if (d.type === 'hello' && state.t) { bc.postMessage({ type: 'major', major: state.major, t: state.t }); }
      };
    }
    window.addEventListener('storage', function (e) {
      var o = e.key === KEY && stored(e.newValue);
      if (o) { setMajor(o.major, 'storage', o.t); }
    });
    document.addEventListener('change', function (e) {
      var t = e.target, act = t.getAttribute('data-act');
      if (t.classList.contains('major-pick')) { setMajor(t.value, 'user'); } else if (act) { state[act] = t.checked; render(); }
    });
    document.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('button[data-list]') : null;
      if (b) { state.jobList = b.getAttribute('data-list'); render(); }
    });
  }

  // ---------- chart tooltips ----------
  var tipEl = null;
  function showTip(el, px, py) {
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.className = 'tip'; tipEl.setAttribute('role', 'tooltip'); tipEl.setAttribute('aria-hidden', 'true');
      document.body.appendChild(tipEl);
    }
    tipEl.innerHTML = el.getAttribute('data-tip').split('\n').map(function (l, i) {
      return i ? esc(l) : '<b>' + esc(l) + '</b>';
    }).join('<br>');
    tipEl.style.display = 'block';
    var w = tipEl.offsetWidth, h = tipEl.offsetHeight, dw = document.documentElement.clientWidth;
    var bodyH = document.body.getBoundingClientRect().height;
    var top = py - h - 12 < window.pageYOffset ? py + 16 : py - h - 12;
    tipEl.style.left = Math.max(4, Math.min(px - w / 2, dw - w - 4)) + 'px';
    tipEl.style.top = Math.max(0, Math.min(top, bodyH - h)) + 'px';   // stay inside the frame (it is sized to the page)
  }
  function hideTip() { if (tipEl) { tipEl.style.display = 'none'; } }
  function watchTips() {
    var target = function (e) { return e.target && e.target.closest ? e.target.closest('[data-tip]') : null; };
    document.addEventListener('mousemove', function (e) {
      var t = target(e);
      if (t) { showTip(t, e.pageX, e.pageY); } else { hideTip(); }
    });
    document.documentElement.addEventListener('mouseleave', hideTip);
    document.addEventListener('click', function (e) {          // touch screens: a tap shows it, a tap elsewhere hides it
      var t = target(e);
      if (t) { showTip(t, e.pageX, e.pageY); } else { hideTip(); }
    });
  }

  // ---------- frame height (Canvas) ----------
  // In a frame, tell the parent page the content height after every change, so Canvas can fit the frame to the
  // panel (Canvas's 'lti.frameResize' message; ledger E45). Outside a frame, or if the parent ignores the message,
  // nothing changes: the frame keeps its fixed height.
  var lastHeight = 0, heightQueued = false;
  function postHeight() {
    heightQueued = false;
    var h = Math.ceil(document.body.getBoundingClientRect().height);
    if (!h || h === lastHeight) { return; }
    lastHeight = h;
    try { window.parent.postMessage(JSON.stringify({ subject: 'lti.frameResize', height: h }), '*'); } catch (e) { /* no parent */ }
  }
  function queueHeight() {
    if (window.parent === window || heightQueued) { return; }
    heightQueued = true;
    (window.requestAnimationFrame || setTimeout)(postHeight);
  }
  function watchHeight() {
    if (window.parent === window) { return; }
    if (window.ResizeObserver) { new ResizeObserver(queueHeight).observe(document.body); }
    document.addEventListener('toggle', queueHeight, true);       // <details> open / close
    window.addEventListener('resize', queueHeight);
    queueHeight();
  }

  // ---------- start ----------
  function getJSON(url) {
    return fetch(url, { cache: 'no-cache' }).then(function (r) {
      if (!r.ok) { throw new Error(url + ': ' + r.status); }
      return r.json();
    });
  }
  function start() {
    var m = /(?:^|[#&])panel=([a-z]+)/.exec(location.hash);
    panels = m && PANELS.indexOf(m[1]) >= 0 ? [m[1]] : PANELS.slice();
    full = panels.length > 1;
    var need = { manifest: true };
    panels.forEach(function (p) { FILES[p].forEach(function (f) { need[f] = true; }); });
    var names = Object.keys(need);
    getJSON('../data/current.json').then(function (cur) {
      var base = '../data/bundles/' + encodeURIComponent(cur.bundle) + '/';
      return Promise.all(names.map(function (n) {
        var g = getJSON(base + n + '.json');
        return n === 'lifetime' ? g.catch(function () { return null; }) : g;   // older bundles have no lifetime.json
      }));
    }).then(function (vals) {
      names.forEach(function (n, i) { D[n] = vals[i]; });
      if (!D.lifetime) { panels = panels.filter(function (p) { return p !== 'lifetime'; }); full = full || false; }
      return fetch('../data/last-checked.json', { cache: 'no-cache' }).then(function (r) {
        if (r.status === 404) { D.lastChecked = 'missing'; return null; }
        if (!r.ok) { D.lastChecked = 'unreadable'; return null; }
        return r.json().then(function (lc) { D.lastChecked = lc; }, function () { D.lastChecked = 'unreadable'; });
      }, function () { D.lastChecked = 'unreadable'; });
    }).then(function () {
      var src = D.rank ? D.rank.measures.unemployment.map(function (r) { return r.major; })
        : D.compare ? Object.keys(D.compare.measures.pay_mid.by_major)
        : D.same_occupation ? Object.keys(D.same_occupation['grad=0'])
        : D.lifetime ? Object.keys(D.lifetime['grad=0'].by_major)
        : Object.keys(D.local['grad=0|fulltime=1'].florida.by_major);
      majors = src.filter(function (x) { return x !== ECON; }).sort();
      var o = null;
      try { localStorage.removeItem(KEY); } catch (e) { /* drop a pick kept by the 2026-10-25 page */ }
      try { o = stored(sessionStorage.getItem(KEY)); } catch (e) { o = null; }
      if (o && (o.major === '' || o.major === ECON || o.major === UNDECIDED || majors.indexOf(o.major) >= 0)) {
        state.major = o.major; state.t = Number(o.t) || 0;
      }
      shell();
      listen();
      watchHeight();
      watchTips();
      render();
      if (bc) { bc.postMessage({ type: 'hello' }); }
      document.documentElement.setAttribute('data-ready', 'true');
    }).catch(function (err) {
      document.getElementById('app').innerHTML = '<p class="status">The data did not load. Try again later.</p>';
      document.documentElement.setAttribute('data-ready', 'error');
      if (window.console) { console.error(err); }
    });
  }
  if (!window.EMD_NO_START) { start(); }
}());
