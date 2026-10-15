(function () {
    var active = null;
    var weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

    function parse(value) {
        var parts = (value || '').split('-').map(Number);
        if (parts.length === 3 && parts.every(Number.isFinite)) return new Date(parts[0], parts[1] - 1, parts[2]);
        return new Date();
    }

    function format(date) {
        return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
    }

    function close() {
        if (active) active.remove();
        active = null;
    }

    function open(input) {
        close();
        var view = parse(input.value);
        var calendar = document.createElement('div');
        calendar.className = 'panel-calendar is-open';
        calendar.setAttribute('role', 'dialog');
        calendar.setAttribute('aria-label', 'Choose date');
        document.body.appendChild(calendar);
        active = calendar;

        function render() {
            var year = view.getFullYear();
            var month = view.getMonth();
            var today = format(new Date());
            var selected = input.value;
            var first = new Date(year, month, 1);
            var days = new Date(year, month + 1, 0).getDate();
            var previousDays = new Date(year, month, 0).getDate();
            var monthNames = Array.from({ length: 12 }, function (_, index) { return new Date(2000, index, 1).toLocaleString(undefined, { month: 'long' }); });
            var yearOptions = '';
            for (var optionYear = new Date().getFullYear() + 10; optionYear >= 1900; optionYear--) {
                yearOptions += '<option value="' + optionYear + '"' + (optionYear === year ? ' selected' : '') + '>' + optionYear + '</option>';
            }
            var monthOptions = monthNames.map(function (name, index) {
                return '<option value="' + index + '"' + (index === month ? ' selected' : '') + '>' + name + '</option>';
            }).join('');
            var html = '<div class="panel-calendar-header"><button type="button" class="panel-calendar-nav" data-month="-1" aria-label="Previous month">&#8249;</button>' +
                '<div class="panel-calendar-selects"><select class="panel-calendar-month" aria-label="Select month">' + monthOptions + '</select>' +
                '<select class="panel-calendar-year" aria-label="Select year">' + yearOptions + '</select></div>' +
                '<button type="button" class="panel-calendar-nav" data-month="1" aria-label="Next month">&#8250;</button></div>' +
                '<div class="panel-calendar-weekdays">' + weekdays.map(function (day) { return '<span class="panel-calendar-weekday">' + day + '</span>'; }).join('') + '</div><div class="panel-calendar-days">';
            for (var i = first.getDay() - 1; i >= 0; i--) html += '<button type="button" class="panel-calendar-day is-muted" data-date="' + format(new Date(year, month - 1, previousDays - i)) + '">' + (previousDays - i) + '</button>';
            for (var day = 1; day <= days; day++) {
                var date = format(new Date(year, month, day));
                var classes = 'panel-calendar-day' + (date === today ? ' is-today' : '') + (date === selected ? ' is-selected' : '');
                html += '<button type="button" class="' + classes + '" data-date="' + date + '">' + day + '</button>';
            }
            var total = first.getDay() + days;
            for (var next = 1; total % 7 !== 0; next++, total++) html += '<button type="button" class="panel-calendar-day is-muted" data-date="' + format(new Date(year, month + 1, next)) + '">' + next + '</button>';
            calendar.innerHTML = html + '</div>';
            calendar.querySelectorAll('[data-month]').forEach(function (button) { button.addEventListener('click', function () {
                var targetMonth = view.getMonth() + Number(button.dataset.month);
                var targetYear = view.getFullYear() + Math.floor(targetMonth / 12);
                targetMonth = ((targetMonth % 12) + 12) % 12;
                var day = Math.min(view.getDate(), new Date(targetYear, targetMonth + 1, 0).getDate());
                view = new Date(targetYear, targetMonth, day);
                render();
            }); });
            calendar.querySelector('.panel-calendar-month').addEventListener('change', function (event) {
                var day = Math.min(view.getDate(), new Date(view.getFullYear(), Number(event.target.value) + 1, 0).getDate());
                view = new Date(view.getFullYear(), Number(event.target.value), day);
                render();
            });
            calendar.querySelector('.panel-calendar-year').addEventListener('change', function (event) {
                var year = Number(event.target.value);
                var day = Math.min(view.getDate(), new Date(year, view.getMonth() + 1, 0).getDate());
                view = new Date(year, view.getMonth(), day);
                render();
            });
            calendar.querySelectorAll('[data-date]').forEach(function (button) { button.addEventListener('click', function () { input.value = button.dataset.date; input.dispatchEvent(new Event('change', { bubbles: true })); close(); }); });
        }
        render();
        var rect = input.getBoundingClientRect();
        var left = Math.min(Math.max(12, rect.left), window.innerWidth - calendar.offsetWidth - 12);
        var top = rect.bottom + 8;
        if (top + 300 > window.innerHeight) top = Math.max(12, rect.top - 300 - 8);
        calendar.style.left = left + 'px';
        calendar.style.top = top + 'px';
    }

    function init() {
        document.querySelectorAll('input[type="date"]').forEach(function (input) {
            if (input.dataset.panelCalendar) return;
            input.dataset.panelCalendar = 'true';
            input.classList.add('panel-calendar-input');
            input.addEventListener('click', function (event) { event.preventDefault(); open(input); });
            input.addEventListener('keydown', function (event) { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(input); } });
        });
    }

    document.addEventListener('click', function (event) { if (active && !active.contains(event.target) && !event.target.matches('input[type="date"]')) close(); });
    document.addEventListener('DOMContentLoaded', init);
    init();
})();
