// ============================================================
// Novel Mode ω Anchors — auto-add anchors + jump-to-marginalia
// ============================================================

function attachOmegaAnchors() {
    const cmLines = document.querySelectorAll('.cm-line');

    cmLines.forEach(line => {
        // find comment spans inside this line
        const comment = line.querySelector('.cm-comment');
        if (!comment) return;

        // avoid duplicating ω
        if (line.querySelector('.inline-omega-anchor')) return;

        // create ω anchor
        const omega = document.createElement('span');
        omega.className = 'inline-omega-anchor';
        omega.textContent = 'ω';

        // insert just after the comment
        comment.insertAdjacentElement('afterend', omega);

        // click → highlight marginalia + place cursor
        omega.addEventListener('click', () => {
            comment.classList.add('omega-highlight');

            // remove the highlight after 1.2 seconds
            setTimeout(() => comment.classList.remove('omega-highlight'), 1200);

            // put cursor inside the comment (enter edit mode)
            const range = document.createRange();
            const sel = window.getSelection();
            range.selectNodeContents(comment);
            sel.removeAllRanges();
            sel.addRange(range);
        });
    });
}

// Run whenever Obsidian updates the DOM
setInterval(attachOmegaAnchors, 600);
