-- Inventory manifests are JSON artifacts stored alongside the original uploads.
-- Keep the bucket private; this only expands the permitted MIME types.
update storage.buckets
set allowed_mime_types = (
  select array_agg(distinct mime)
  from unnest(coalesce(allowed_mime_types, '{}'::text[]) || array['application/json']::text[]) as mime
)
where id = 'exam-inbox';
