-- The frontend uses Supabase anonymous sign-in. Such sessions have the
-- Postgres role "authenticated", not "anon". Restrict the temporary hidden
-- admin access to JWTs explicitly marked as anonymous.
create policy "Temporary anonymous-session access to exam jobs"
on public.exam_ingest_jobs
for all to authenticated
using (coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false))
with check (coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false));

create policy "Temporary anonymous-session access to exam events"
on public.exam_ingest_events
for all to authenticated
using (coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false))
with check (coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false));

create policy "Temporary anonymous-session upload to exam inbox"
on storage.objects
for insert to authenticated
with check (
  bucket_id = 'exam-inbox'
  and coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false)
);

create policy "Temporary anonymous-session read exam inbox"
on storage.objects
for select to authenticated
using (
  bucket_id = 'exam-inbox'
  and coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false)
);

create policy "Temporary anonymous-session update exam inbox"
on storage.objects
for update to authenticated
using (
  bucket_id = 'exam-inbox'
  and coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false)
)
with check (
  bucket_id = 'exam-inbox'
  and coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false)
);

create policy "Temporary anonymous-session delete exam inbox"
on storage.objects
for delete to authenticated
using (
  bucket_id = 'exam-inbox'
  and coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false)
);
