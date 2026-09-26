from django import forms


class AssignmentImportForm(forms.Form):
    course_name = forms.CharField(max_length=200, label="Course name")
    github_organization = forms.CharField(max_length=100, label="GitHub organization")
    assignment_name = forms.CharField(max_length=200, label="Assignment name")
    template_repository = forms.CharField(
        max_length=100,
        label="Existing template repository",
        help_text="The repository used to create student repositories.",
    )
    due_at = forms.DateTimeField(
        label="Due date and time",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )
    late_penalty = forms.IntegerField(label="Late penalty", initial=-2)

    def __init__(self, *args, organizations=None, templates=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organizations:
            self.fields["github_organization"] = forms.ChoiceField(
                choices=[(item["login"], item["login"]) for item in organizations],
                label="GitHub organization",
            )
        if templates:
            selected_organization = self.data.get("github_organization", "")
            if selected_organization:
                templates = [
                    item
                    for item in templates
                    if item["organization"] == selected_organization
                ]
            self.fields["template_repository"] = forms.ChoiceField(
                choices=[
                    (item["name"], f"{item['organization']} / {item['name']}")
                    for item in templates
                ],
                label="Existing template repository",
                help_text="Choose a repository already marked as a GitHub template.",
            )
