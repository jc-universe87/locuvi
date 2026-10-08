# Acceptance tests / definition of done

## Invoice behaviour
- [ ] Personal identity and bank details saved; practice saved.
- [ ] Multiple work dates within same calendar month entered with differing rates.
- [ ] Accurate GBP fee subtotal, pensionable base and 14.38% employer addition.
- [ ] £600 eligible fee produces £540 pensionable pay, £77.65 employer contribution and £677.65 invoice total.
- [ ] Non-pensionable line excluded from pension addition.
- [ ] Pensionable entries spanning two calendar months blocked or offered split.
- [ ] Draft editable; preview has no issued number.
- [ ] Double-click/parallel issue cannot issue twice; numbering remains unique.
- [ ] Issued snapshot/PDF unchanged after practice or bank settings edit.
- [ ] Issued PDF contains legal invoice essentials; typography/page breaks verified.
- [ ] Void retains original number and original PDF; no delete.
- [ ] App restart retains records and exact original PDFs.

## WebDAV
- [ ] Feature off: invoice issue/download works normally.
- [ ] With valid disposable Nextcloud/WebDAV endpoint, file uploaded to selected hierarchy.
- [ ] Folder hierarchy created where absent.
- [ ] No overwrite of different content at same target path.
- [ ] Duplicate retry recognises already uploaded matching file.
- [ ] Bad credentials produce a clear actionable state without losing invoice.
- [ ] Offline remote: issue works, job retained for retry and eventually syncs.
- [ ] Interrupted upload/restart safe.
- [ ] SSRF checks, URL/redirect validation and TLS verification covered.
- [ ] Secret never returned by GET config or printed in logs.
- [ ] Remote status shown truthfully; do not falsely mark synced.

## Deployment
- [ ] Docker image builds with pinned dependencies.
- [ ] Tests pass and output documented.
- [ ] Private binding; non-root image where feasible; production debug disabled.
- [ ] Persistent volumes with working restore path.
- [ ] Full README for owner setup, WebDAV app password and backup.
- [ ] No secret or genuine private details committed.
