SAMPLE_BANK = [
    {
        "title": "Sample TOEFL Reading",
        "default_minutes": 18,
        "passage": (
            "Urban Trees and Microclimates\n\n"
            "Cities often experience higher temperatures than surrounding rural areas, "
            "a phenomenon known as the urban heat island effect. One reason is that "
            "materials like asphalt and concrete absorb and re-radiate heat. Urban trees "
            "can mitigate this by providing shade and through evapotranspiration."
        ),
        "questions": [
            {
                "id": "q1",
                "type": "single",
                "prompt": "According to the passage, one cause of the urban heat island effect is:",
                "choices": [
                    ("A", "Higher city elevation"),
                    ("B", "Asphalt and concrete absorb and re-radiate heat"),
                    ("C", "Trees heat the air"),
                    ("D", "Rural areas generate more heat"),
                ],
                "correct": ["B"],
                "explanation": "The passage says asphalt and concrete absorb and re-radiate heat.",
            },
            {
                "id": "q2",
                "type": "multi",
                "prompt": "Which TWO mechanisms are mentioned as ways trees can cool cities?",
                "choices": [
                    ("A", "Providing shade"),
                    ("B", "Evapotranspiration"),
                    ("C", "Increasing asphalt coverage"),
                    ("D", "Stopping wind permanently"),
                ],
                "correct": ["A", "B"],
                "explanation": "The passage mentions shade and evapotranspiration.",
            },
        ],
    }
]

print("[DEBUG] SAMPLE_BANK[0] questions =", len(SAMPLE_BANK[0].get("questions", [])))
