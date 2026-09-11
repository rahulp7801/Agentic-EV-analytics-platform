# Supabase database trust

`supabase-prod-ca-2021.crt` is a public CA certificate, not a private key.
Downloaded over HTTPS from the URL configured in Supabase's own dashboard:
https://github.com/supabase/supabase/blob/master/apps/studio/hooks/custom-content/custom-content.json

Source: https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt

SHA256: `700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7`

Python worker URLs use `sslmode=verify-full&sslrootcert=certs/supabase-prod-ca-2021.crt`
from the repository root. Vercel uses `sslmode=verify-full` in the reader URL and
the certificate's PEM contents in server-only `DATABASE_SSL_CA`. The dashboard
passes the CA explicitly to pg with certificate/hostname verification enabled.
Do not disable verification on certificate rotation; obtain the replacement from
the official provider, verify its provenance, test it, and update this record.
