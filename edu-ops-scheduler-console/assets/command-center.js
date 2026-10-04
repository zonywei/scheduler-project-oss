
(function () {
  let toastNode;
  function toast(message) {
    if (!toastNode) {
      toastNode = document.createElement('div');
      toastNode.className = 'toast';
      document.body.appendChild(toastNode);
    }
    toastNode.textContent = message || '操作已记录';
    toastNode.classList.add('is-visible');
    clearTimeout(toastNode._timer);
    toastNode._timer = setTimeout(function () { toastNode.classList.remove('is-visible'); }, 1800);
  }

  document.querySelectorAll('[data-toast]').forEach(function (node) {
    node.addEventListener('click', function () {
      toast(node.getAttribute('data-toast'));
    });
  });

  document.querySelectorAll('[data-filter-table]').forEach(function (input) {
    const table = document.querySelector(input.getAttribute('data-filter-table'));
    if (!table) return;
    input.addEventListener('input', function () {
      const value = input.value.trim().toLowerCase();
      table.querySelectorAll('tbody tr').forEach(function (row) {
        row.hidden = value && !row.textContent.toLowerCase().includes(value);
      });
    });
  });

  document.querySelectorAll('[data-validate-file]').forEach(function (button) {
    button.addEventListener('click', function () {
      const row = button.closest('tr');
      const status = row && row.querySelector('[data-file-status]');
      if (status) {
        status.className = 'badge ok';
        status.textContent = '已校验';
      }
      button.textContent = '重新校验';
      toast('字段、列名和指纹校验完成');
    });
  });

  document.querySelectorAll('[data-severity-filter]').forEach(function (button) {
    button.addEventListener('click', function () {
      const target = button.getAttribute('data-severity-filter');
      document.querySelectorAll('[data-severity-filter]').forEach(function (item) {
        item.classList.toggle('is-active', item === button);
      });
      document.querySelectorAll('[data-severity]').forEach(function (row) {
        row.hidden = target !== 'all' && row.getAttribute('data-severity') !== target;
      });
    });
  });

  const form = document.querySelector('[data-nl-form]');
  if (form) {
    const input = form.querySelector('[name="rule_text"]');
    const target = document.querySelector('[data-rule-draft]');
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      const text = (input.value || '').trim();
      if (!text) {
        toast('先输入一条规则');
        return;
      }
      const day = (text.match(/周[一二三四五六日天]|星期[一二三四五六日]/) || ['未识别日期'])[0].replace('周天', '周日');
      const slot = (text.match(/早自习|上午[1-4]|下午[1-4]|晚自习[12]?/) || ['待人工确认节次'])[0];
      target.innerHTML = '<div class="rule-card"><strong>解析结果 · ' + escapeHtml(day) + ' ' + escapeHtml(slot) + '</strong><span>' + escapeHtml(text) + '</span><b class="badge warn">待确认</b></div>';
      toast('已生成规则草稿');
    });
  }

  const run = document.querySelector('[data-start-run]');
  if (run) {
    run.addEventListener('click', function () {
      const fill = document.querySelector('[data-run-progress]');
      const label = document.querySelector('[data-run-label]');
      const log = document.querySelector('[data-run-log]');
      let value = 35;
      run.disabled = true;
      label.textContent = '求解进行中';
      const timer = setInterval(function () {
        value = Math.min(100, value + 13);
        if (fill) fill.style.setProperty('--p', value + '%');
        if (log) {
          log.textContent += '\\n[候选] 进度 ' + value + '%：保留更优候选';
          log.scrollTop = log.scrollHeight;
        }
        if (value >= 100) {
          clearInterval(timer);
          run.disabled = false;
          run.textContent = '再次求解';
          label.textContent = '完成，可查看结果交付';
          label.className = 'badge ok';
          toast('求解批次已完成');
        }
      }, 420);
    });
  }

  document.querySelectorAll('[data-timetable-view]').forEach(function (button) {
    button.addEventListener('click', function () {
      const view = button.getAttribute('data-timetable-view');
      document.querySelectorAll('[data-timetable-view]').forEach(function (item) {
        item.classList.toggle('is-active', item === button);
      });
      const title = document.querySelector('[data-timetable-title]');
      if (title) {
        title.textContent = view === 'teacher'
          ? '教师E · 教师课表'
          : view === 'room'
            ? '实验楼 201 · 场地课表'
            : '匿名班级A · 班级课表';
      }
      toast(view === 'teacher' ? '已切换到教师视图' : view === 'room' ? '已切换到场地视图' : '已切换到班级视图');
    });
  });

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
})();
