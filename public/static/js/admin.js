/* Admin-specific JS */
function pollJobStatus(jobId) {
    fetch('/admin/mapreduce/' + jobId + '/status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            const bar = document.getElementById('job-progress-' + jobId);
            const status = document.getElementById('job-status-' + jobId);
            if (bar) bar.style.width = data.progress + '%';
            if (status) status.textContent = data.status;
            if (data.status === 'running') {
                setTimeout(function() { pollJobStatus(jobId); }, 5000);
            }
        })
        .catch(function() {});
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.job-progress-bar').forEach(function(bar) {
        const jobId = bar.getAttribute('data-job-id');
        if (jobId) pollJobStatus(jobId);
    });
});
