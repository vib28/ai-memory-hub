### 🧩 **Prompt: Chat Summarizer for Cold Start Continuation**

You are an expert conversation analyst and summarizer.
Your task is to read this entire chat transcript between a user (me) and an assistant (you), then produce a **detailed, structured summary** that preserves the **user's goals, reasoning, and iterative refinements** above all else.

#### **Instructions:**

1. **Analyze the chat from start to finish**, focusing on:

   * The user's evolving intent, objectives, and reasoning process.
   * Key points of clarification or reiteration that reveal what the user truly wanted.
   * Critical assistant insights or solutions that shaped progress (summarize briefly).
   * Any **open threads, unfinished work, or next steps** the user planned or implied.

2. **Weigh user inputs more heavily than assistant outputs.**
   Treat repeated or refined user statements as signals of priority.

3. **Produce your output in the following structure:**

    ## Cold Start Summary

   ### Context
   [Summarize the overall topic, background, and purpose of the conversation.]

   ### User Goals and Reasoning
   [Explain what the user is trying to accomplish, why it matters, and how their thinking evolved.]

   ### Key Progress and Decisions
   [Summarize main conclusions, choices, or agreed directions reached in the chat.]

   ### Open Threads and Next Actions
   [List unresolved issues, pending steps, or ideas the user wanted to pursue next.]

   ### Continuation Guidance
   [Optionally include 1–2 sentences instructing a new assistant on how to seamlessly continue the work.]
 

4. **Tone and length:**

   * Write in a clear, factual, and professional tone.
   * Be **detailed** — typically **200–400 words**.
   * Avoid quoting or copying from the transcript; paraphrase insightfully.
