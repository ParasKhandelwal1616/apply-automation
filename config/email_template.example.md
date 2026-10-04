# Application email template

The bot builds emails from `config/profile.yaml` (name, college, proof_points, links).
Copy this file to `email_template.md` only if you want a human-readable reminder.

## Subject

`Application for [Exact Role Title] — [Your Name]`

If the posting specifies a subject format, the bot follows that.

## Body

```
Hi [Team],

[Hook from your skills]

My background matches what you're looking for:

[JD requirement]: [proof_point from your profile]

[Closing from profile notes / college / batch]

Resume / Portfolio / GitHub / LinkedIn from profile.yaml

Best regards,
[Your Name]
[email] | [phone]
```

## Rules

1. Never invent skills. Only what is in profile.yaml.
2. Use real numbers from your proof_points.
3. Personal Gmail apply addresses stay Draft (not auto-sent).
