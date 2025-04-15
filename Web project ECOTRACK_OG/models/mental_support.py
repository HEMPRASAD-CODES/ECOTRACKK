from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

model_name = "mrm8488/t5-base-finetuned-e2m-intent"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSeq2SeqLM.from_pretrained(model_name)



def ask_mental(prompt):
    input_ids = tokenizer(prompt, return_tensors="pt").input_ids
    output = model.generate(input_ids, max_length=256)
    return tokenizer.decode(output[0], skip_special_tokens=True)
